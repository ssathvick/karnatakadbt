"""Fresh-install admission, distinct from historical migration acceptance.

Only a new local database bound to this installation can use this path. It does
not manufacture a migration, rollback or production-acceptance receipt.
"""
import os,json,uuid,hashlib
from pathlib import Path
from contextlib import contextmanager
from sqlalchemy import text,create_engine
from cryptography.fernet import Fernet

ROOT=Path('/runtime')
def identity():
    if os.environ.get('KDBT_DEPLOYMENT_MODE')!='local':raise ValueError('Fresh local profile required')
    value=json.loads((ROOT/'installation.json').read_text())
    if value.get('kind')!='fresh-local-install':raise ValueError('Existing production/migration state cannot use local admission')
    return str(uuid.UUID(value['installation_id']))

class LocalOwnership:
    def __init__(self,engine,scope):self.engine,self.scope=engine,scope;self.installation=identity()
    @contextmanager
    def admission(self,owner='NATIVE'):
        if owner!='NATIVE':raise ValueError('Fresh installations admit only their native writer')
        with self.engine.begin() as c:
            c.execute(text('SELECT pg_advisory_xact_lock_shared(hashtextextended(:scope,0))'),{'scope':'karnatakadbt-local:'+self.scope})
            row=c.execute(text('SELECT installation_id::text,owner FROM kdbt_local_control.installation WHERE singleton')).one()
            if tuple(row)!=(self.installation,'NATIVE'):raise ValueError('Local writer identity is fenced')
            yield
    @contextmanager
    def acquire(self):
        with self.admission():yield True
    def writer(self):return self.admission()

class RegistryAdmission(LocalOwnership):
    pass

def configure_writer(engine,settings,scope):
    if settings.get('business_writes_enabled') is not True:return None
    return LocalOwnership(engine,scope)

class LocalJournal:
    def __init__(self,engine,key):self.engine=engine;self.cipher=Fernet(key)
    def initialize(self):
        with self.engine.begin() as c:c.execute(text('CREATE TABLE IF NOT EXISTS kdbt_local_control.registry_journal(id text PRIMARY KEY,digest text NOT NULL,ciphertext text NOT NULL)'))
    def append(self,c,operation_id,writer,changes):
        raw=json.dumps({'writer':writer,'changes':changes},sort_keys=True,separators=(',',':')).encode();digest=hashlib.sha256(raw).hexdigest()
        prior=c.execute(text('SELECT digest FROM kdbt_local_control.registry_journal WHERE id=:id'),{'id':operation_id}).scalar_one_or_none()
        if prior is not None:
            if prior!=digest:raise ValueError('Changed content reused a registry journal operation')
            return
        c.execute(text('INSERT INTO kdbt_local_control.registry_journal VALUES(:id,:digest,:ciphertext)'),{'id':operation_id,'digest':digest,'ciphertext':self.cipher.encrypt(raw).decode()})

def portal_writer(settings):
    from registry_portal_writer import NativePortalRegistryWriter
    from registry_approval_store import RegistryApprovalStore
    class LocalPortalWriter(NativePortalRegistryWriter):
        def authorize(self,c):
            current=c.execute(text('SELECT installation_id::text,owner FROM kdbt_local_control.installation WHERE singleton')).one()
            if tuple(current)!=(identity(),'NATIVE'):raise ValueError('Portal writer identity is fenced')
    engine=create_engine(settings['url'],hide_parameters=True,pool_pre_ping=True)
    journal=LocalJournal(engine,(ROOT/'keys/registry-journal.key').read_bytes())
    result=LocalPortalWriter(RegistryApprovalStore(engine),scope='local-registry',reverse_journal=journal);result.initialize();return result

def install_profile():
    identity()
    import registry_worker_admission
    registry_worker_admission.RegistryWorkerAdmission=RegistryAdmission
    import native_administration_admission
    native_administration_admission.configure_writer=configure_writer
    import native_master_data_ownership
    native_master_data_ownership.configure_master_writer=lambda engine,settings:configure_writer(engine,settings,'master-data')
    # A fresh deployment has no Java sessions to recover. Keep CAS and absolute
    # Redis expiry while using an own, versioned JSON data format.
    import base64
    from native_auth_cache import AuthenticationFailure
    class JSONSessionCodec:
        def __init__(self,templates):pass
        def encode(self,value,template='transaction',rebuild_fields=()):
            return b'KDBTJSON1.'+json.dumps({k:v for k,v in value.items() if k!='_wire'},ensure_ascii=False,separators=(',',':')).encode()
        def decode(self,raw):
            if not isinstance(raw,bytes) or not raw.startswith(b'KDBTJSON1.') or len(raw)>1024*1024:raise AuthenticationFailure('invalid_session_format')
            value=json.loads(raw[10:]);value['_wire']=base64.b64encode(raw).decode();return value
    import native_auth_cache
    native_auth_cache.JavaSessionCodec=JSONSessionCodec
