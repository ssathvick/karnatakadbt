"""Encrypted native authentication state and separate safe console read views."""
import json
from cryptography.fernet import Fernet
from psycopg2 import sql
from registry_auxiliary_sync import NativeAuxiliaryProjector,digest_key

PROVIDER_FIELDS=['provider_id','register_id','provider_name','provider_description','adapter_name','display_order','is_active']
HISTORY_FIELDS=['authentication_id','register_id','internal_record_id','initiated_at','status','authentication_method','initiated_by_staff_id','claim_verifications','expiry_at','failure_reason']


class NativeIdentityProjector(NativeAuxiliaryProjector):
    def __init__(self,native_schema='public',*,encryption_key):
        super().__init__(native_schema);self.cipher=Fernet(encryption_key.encode())
        self.mapping={'g2p_registrant_authentication_providers':('provider','provider_id'),'g2p_registrant_authentications':('attempt','authentication_id')}

    def encode_state(self,raw):return self.cipher.encrypt(raw.encode()).decode()
    def decode_state(self,raw):
        try:return self.cipher.decrypt(raw.encode()).decode()
        except Exception:raise ValueError('NATIVE_IDENTITY_STATE_UNREADABLE') from None

    def source_key(self,table,raw):
        value=json.loads(raw)[self.mapping[table][1]]
        if not value:raise ValueError('Missing authentication identity')
        return digest_key([value])

    def outputs(self,c,table,raw):
        kind,key=self.mapping[table];value=json.loads(raw)
        secret=raw
        if kind=='provider' and isinstance(value.get('client_private_key'),str) and value['client_private_key'].startswith('\\x'):
            decoded=bytes.fromhex(value['client_private_key'][2:]).decode()
            c.execute("SELECT jsonb_set(%s::jsonb,'{client_private_key}',%s::jsonb)::text",(raw,json.dumps(decoded)));secret=c.fetchone()[0]
        allowed=PROVIDER_FIELDS if kind=='provider' else HISTORY_FIELDS
        c.execute("SELECT jsonb_object_agg(k,v)::text FROM jsonb_each(%s::jsonb) e(k,v) WHERE k=ANY(%s)",(raw,allowed));safe=c.fetchone()[0]
        attrs={'register_id':value['register_id'],'record_id':value.get('internal_record_id') if kind=='attempt' else None,'initiated_at':value.get('initiated_at') if kind=='attempt' else None,'is_active':value.get('is_active') if kind=='provider' else None,'display_order':value.get('display_order') if kind=='provider' else None}
        return [('console_registrant_auth_secrets',{'kind':kind,'id':value[key]},{'expires_at':None},secret),('console_registrant_auth_views',{'kind':'provider' if kind=='provider' else 'history','id':value[key]},attrs,safe)]

    def assert_output(self,c,output,allow_missing=False):
        target,keys,_,raw=output
        if target!='console_registrant_auth_secrets':return super().assert_output(c,output,allow_missing)
        c.execute(sql.SQL('SELECT ciphertext,expires_at FROM {}.{} WHERE {} FOR UPDATE').format(sql.Identifier(self.schema),sql.Identifier(target),self.predicate(keys)),tuple(keys.values()));row=c.fetchone()
        if row is None and allow_missing:return False
        if row is None:raise ValueError('NATIVE_IDENTITY_SYNC_CONFLICT')
        decrypted=self.decode_state(row[0]);c.execute('SELECT %s::jsonb=%s::jsonb',(decrypted,raw))
        if not c.fetchone()[0] or row[1] is not None:raise ValueError('NATIVE_IDENTITY_SYNC_CONFLICT')
        return True

    def put_output(self,c,output):
        target,keys,_,raw=output
        if target!='console_registrant_auth_secrets':return super().put_output(c,output)
        c.execute(sql.SQL('INSERT INTO {}.{}(kind,id,ciphertext,expires_at) VALUES(%s,%s,%s,NULL) ON CONFLICT(kind,id) DO UPDATE SET ciphertext=excluded.ciphertext,expires_at=NULL').format(sql.Identifier(self.schema),sql.Identifier(target)),(keys['kind'],keys['id'],self.encode_state(raw)))

    def namespace_outputs(self,table):
        kind,_=self.mapping[table]
        return [('console_registrant_auth_secrets',{'kind':kind}),('console_registrant_auth_views',{'kind':'provider' if kind=='provider' else 'history'})]
