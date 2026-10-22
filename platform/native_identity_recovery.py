"""Encrypted identity-effect intents, reconciled against committed IAM SQL.

Deletion retires and renames the original Keycloak object, retaining its UUID,
secret, memberships and composite graph. No realm snapshot is overwritten.
Reconciliation takes the same lock as native IAM business transactions.
"""
import hashlib,json,secrets,uuid
from urllib.parse import quote
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import text
from native_iam_business import IamBusinessError

MARKER='kdbt-recovery-effect'
RETIRED='__kdbt_retired_'
ENTITIES={'application':('staff_portal_applications','id'),
          'role':('staff_roles','id'),'policy':('data_policies','policy_id')}
LOCK='karnatakadbt-native-iam-business'

class IdentityRecoveryBlocked(IamBusinessError):pass

class RecoverableIdentityAdmin:
    def __init__(self,engine,admin,key,*,allowed_prefix=None):
        if not isinstance(key,str) or len(key)<40:raise ValueError('Private identity recovery key required')
        self.engine,self.admin,self.allowed_prefix=engine,admin,allowed_prefix
        self.crypto=AESGCM(hashlib.sha256(key.encode()).digest());self.bound=None

    def initialize(self):
        with self.engine.begin() as c:
            c.execute(text('CREATE SCHEMA IF NOT EXISTS kdbt_iam_identity_effects'))
            c.execute(text('REVOKE ALL ON SCHEMA kdbt_iam_identity_effects FROM PUBLIC'))
            c.execute(text("CREATE TABLE IF NOT EXISTS kdbt_iam_identity_effects.intents(id uuid PRIMARY KEY,ordinal bigint GENERATED ALWAYS AS IDENTITY,state text NOT NULL CHECK(state IN ('PENDING','COMMITTED','COMPENSATED','SKIPPED')),payload bytea NOT NULL)"))
            c.execute(text('REVOKE ALL ON ALL TABLES IN SCHEMA kdbt_iam_identity_effects FROM PUBLIC'))

    def bind_business_entity(self,kind,identifier):
        if kind not in ENTITIES or identifier is None:raise ValueError('Exact business entity required')
        self.bound={'kind':kind,'identifier':str(identifier)}

    def guard(self,application):
        if self.allowed_prefix is not None and not application.startswith(self.allowed_prefix):
            raise IdentityRecoveryBlocked('Identity recovery namespace differs')

    def seal(self,identifier,value):
        nonce=secrets.token_bytes(12)
        return nonce+self.crypto.encrypt(nonce,json.dumps(value).encode(),identifier.encode())

    def open(self,identifier,value):
        value=bytes(value)
        try:return json.loads(self.crypto.decrypt(value[:12],value[12:],identifier.encode()))
        except Exception:raise IdentityRecoveryBlocked('Identity recovery ciphertext cannot be verified') from None

    def intent(self,operation,application,**values):
        self.guard(application)
        if self.bound is None:raise IdentityRecoveryBlocked('Identity operation lacks SQL entity binding')
        identifier=str(uuid.uuid4());payload={'entity':self.bound,'operation':operation,'application':application,**values}
        self.bound=None
        with self.engine.begin() as c:
            c.execute(text("INSERT INTO kdbt_iam_identity_effects.intents(id,state,payload) VALUES(CAST(:id AS uuid),'PENDING',:payload)"),{'id':identifier,'payload':self.seal(identifier,payload)})
        return identifier

    def finish(self,identifier,state):
        with self.engine.begin() as c:
            c.execute(text('UPDATE kdbt_iam_identity_effects.intents SET state=:state WHERE id=CAST(:id AS uuid)'),{'state':state,'id':identifier})

    def client(self,name):
        self.guard(name);identifier=self.admin.resolve(name)
        if not identifier:return None
        result=self.admin.call('GET','/clients/'+quote(identifier,safe=''))
        if not isinstance(result,dict) or not result.get('id'):raise IdentityRecoveryBlocked('Identity client disappeared')
        return result

    def role(self,client_id,name):
        result=self.admin.call('GET','/clients/'+quote(client_id,safe='')+'/roles/'+quote(name,safe=''))
        if isinstance(result,dict) and result.get('not_found'):return None
        if not isinstance(result,dict) or not result.get('id'):raise IdentityRecoveryBlocked('Identity role lookup invalid')
        return result

    def create_client(self,name,description=None):
        if self.client(name):self.bound=None;return name,True
        identifier=self.intent('create_client',name)
        result=self.admin.call('POST','/clients',body={'clientId':name,'enabled':True,'protocol':'openid-connect','publicClient':False,'clientAuthenticatorType':'client-secret','attributes':{MARKER:identifier},**({'description':description} if description else {})})
        if isinstance(result,dict) and result.get('conflict'):
            self.finish(identifier,'SKIPPED');return name,True
        return name,False

    def create_role(self,name,application,role_description=None):
        self.guard(application);client=self.admin.resolve(application)
        if not client:raise IdentityRecoveryBlocked('Identity application missing')
        if self.role(client,name):self.bound=None;return name,True
        identifier=self.intent('create_role',application,client_id=client,name=name)
        result=self.admin.call('POST','/clients/'+quote(client,safe='')+'/roles',body={'name':name,'attributes':{MARKER:[identifier]},**({'description':role_description} if role_description else {})})
        if isinstance(result,dict) and result.get('conflict'):
            self.finish(identifier,'SKIPPED');return name,True
        return name,False

    def retire(self,operation,application,before,client_id=None):
        if not before:self.bound=None;return False
        old=before['clientId'] if operation=='delete_client' else before['name']
        # Only fields changed by retirement are retained. Secrets and role graphs
        # stay in Keycloak and are never exported into this journal.
        kept={key:before.get(key) for key in (['clientId','enabled','attributes'] if operation=='delete_client' else ['name','description','attributes','composite'])}
        kept['attributes']=dict(before.get('attributes') or {})
        identifier=self.intent(operation,application,object_id=before['id'],client_id=client_id,name=old,before=kept)
        retired=RETIRED+identifier.replace('-','');attributes=dict(before.get('attributes') or {})
        attributes[MARKER]=identifier if operation=='delete_client' else [identifier]
        body={'clientId':retired,'enabled':False,'attributes':attributes} if operation=='delete_client' else {'name':retired,'description':before.get('description'),'composite':before.get('composite',False),'attributes':attributes}
        path='/clients/'+quote(before['id'],safe='') if operation=='delete_client' else '/clients/'+quote(client_id,safe='')+'/roles/'+quote(old,safe='')
        result=self.admin.call('PUT',path,body=body)
        if isinstance(result,dict) and (result.get('not_found') or result.get('conflict')):raise IdentityRecoveryBlocked('Identity retirement outcome requires reconciliation')
        return True

    def delete_client(self,name):return self.retire('delete_client',name,self.client(name))

    def delete_role(self,name,application):
        self.guard(application);client=self.admin.resolve(application)
        if not client:raise IdentityRecoveryBlocked('Identity application missing')
        return self.retire('delete_role',application,self.role(client,name),client)

    def reconcile(self):
        counts={'committed':0,'compensated':0}
        with self.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as lock:
            if not lock.execute(text('SELECT pg_try_advisory_lock(hashtextextended(:key,0))'),{'key':LOCK}).scalar_one():raise IdentityRecoveryBlocked('IAM business operation is still active')
            try:
                rows=lock.execute(text("SELECT id::text,payload FROM kdbt_iam_identity_effects.intents WHERE state='PENDING' ORDER BY ordinal DESC")).all()
                for identifier,cipher in rows:
                    value=self.open(identifier,cipher);self.guard(value['application']);kind=value['entity']['kind']
                    if kind not in ENTITIES:raise IdentityRecoveryBlocked('Identity recovery entity differs')
                    table,pk=ENTITIES[kind]
                    present=lock.execute(text('SELECT EXISTS(SELECT 1 FROM public.'+table+' WHERE '+pk+'::text=:id)'),{'id':value['entity']['identifier']}).scalar_one()
                    operation=value['operation'];create=operation.startswith('create_');is_client=operation.endswith('client')
                    retired=RETIRED+identifier.replace('-','')
                    if create:
                        obj=self.client(value['application']) if is_client else self.role(value['client_id'],value['name'])
                    elif is_client:
                        obj=self.admin.call('GET','/clients/'+quote(value['object_id'],safe=''))
                    else:
                        obj=self.role(value['client_id'],retired) or self.role(value['client_id'],value['name'])
                    marker=(obj or {}).get('attributes',{}).get(MARKER)
                    marked=marker==identifier or marker==[identifier]
                    if create:
                        if not obj:
                            if present:raise IdentityRecoveryBlocked('Committed identity creation is missing')
                        elif not marked:raise IdentityRecoveryBlocked('Identity creation is not owned by this intent')
                        elif not present:
                            path='/clients/'+quote(obj['id'],safe='') if is_client else '/clients/'+quote(value['client_id'],safe='')+'/roles/'+quote(value['name'],safe='')
                            result=self.admin.call('DELETE',path)
                            if isinstance(result,dict) and result.get('conflict'):raise IdentityRecoveryBlocked('Identity compensation conflicted')
                            remaining=self.client(value['application']) if is_client else self.role(value['client_id'],value['name'])
                            if remaining is not None:raise IdentityRecoveryBlocked('Identity compensation not observed')
                    else:
                        if not obj or obj.get('id')!=value['object_id']:raise IdentityRecoveryBlocked('Retained identity object is missing')
                        name=obj.get('clientId' if is_client else 'name')
                        if marked and name==retired:
                            if present:
                                path='/clients/'+quote(obj['id'],safe='') if is_client else '/clients/'+quote(value['client_id'],safe='')+'/roles/'+quote(retired,safe='')
                                result=self.admin.call('PUT',path,body=value['before'])
                                if isinstance(result,dict) and (result.get('not_found') or result.get('conflict')):raise IdentityRecoveryBlocked('Identity restoration conflicted')
                                restored=self.admin.call('GET','/clients/'+quote(obj['id'],safe='')) if is_client else self.role(value['client_id'],value['name'])
                                if not restored or restored.get('id')!=value['object_id'] or any((restored.get(k) or {})!=v if k=='attributes' else restored.get(k)!=v for k,v in value['before'].items()):raise IdentityRecoveryBlocked('Identity restoration not observed')
                        elif present and name==value['name'] and all((obj.get(k) or {})==v if k=='attributes' else obj.get(k)==v for k,v in value['before'].items()):pass
                        else:raise IdentityRecoveryBlocked('Retained identity was modified outside recovery')
                    state='COMMITTED' if present==create else 'COMPENSATED'
                    self.finish(identifier,state);counts[state.lower()]+=1
            finally:lock.execute(text('SELECT pg_advisory_unlock(hashtextextended(:key,0))'),{'key':LOCK})
        return counts
