"""Transactional encrypted consent submission outbox and idempotent replay.

The exact approval body is captured with its pending policy. A lost HTTP reply
reuses that body, service identity and idempotency key after process restart.
Workers must additionally hold production writer admission before dispatch.
"""
import hashlib,json,secrets
import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import text
from native_consent_policy import ConsentPolicyError

class ConsentApprovalDelivery:
    def __init__(self,engine,key,*,policy_key,service_subject,callback_url=None,callback_secret_id=None):
        if not isinstance(key,str) or len(key)<40 or not policy_key or not service_subject:raise ValueError('Private outbox key, approval policy and service identity required')
        self.engine=engine;self.crypto=AESGCM(hashlib.sha256(key.encode()).digest());self.policy_key=policy_key;self.subject=service_subject;self.callback_url=callback_url;self.callback_secret_id=callback_secret_id
    def initialize(self):
        with self.engine.begin() as c:
            c.execute(text('CREATE SCHEMA IF NOT EXISTS kdbt_consent_delivery'))
            c.execute(text('REVOKE ALL ON SCHEMA kdbt_consent_delivery FROM PUBLIC'))
            c.execute(text("CREATE TABLE IF NOT EXISTS kdbt_consent_delivery.jobs(policy_id text PRIMARY KEY,payload bytea NOT NULL,state text NOT NULL CHECK(state IN ('PENDING','DELIVERED')),request_id text)"))
            c.execute(text('REVOKE ALL ON ALL TABLES IN SCHEMA kdbt_consent_delivery FROM PUBLIC'))
    def enqueue(self,c,policy,partner):
        identifier=policy['id'];context={'partner_label':partner['name'] or partner['partner_mgmt_id'] or partner['audience'],'partner_mgmt_id':partner['partner_mgmt_id'],'controller_id':partner['controller_id'],'policy_version':policy['version'],'allowed_data_scopes':policy['allowed_data_scopes'],'allowed_purposes':policy['allowed_purposes']}
        payload={'policy_key':self.policy_key,'artifact_type':'consent_manager.policy_change','artifact_id':identifier,'context':context,'callback_url':self.callback_url,'callback_secret_id':self.callback_secret_id,'requester':None}
        nonce=secrets.token_bytes(12);cipher=nonce+self.crypto.encrypt(nonce,json.dumps(payload).encode(),identifier.encode())
        c.execute(text("INSERT INTO kdbt_consent_delivery.jobs(policy_id,payload,state) VALUES(:id,:payload,'PENDING')"),{'id':identifier,'payload':cipher})
    async def deliver(self,identifier,service_token,call):
        with self.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as lock:
            key='kdbt-consent-approval-delivery:'+identifier
            if not lock.execute(text('SELECT pg_try_advisory_lock(hashtextextended(:key,0))'),{'key':key}).scalar_one():raise ConsentPolicyError(409,'Consent approval delivery is already active')
            try:
                job=lock.execute(text('SELECT * FROM kdbt_consent_delivery.jobs WHERE policy_id=:id'),{'id':identifier}).mappings().one_or_none()
                if job is None:raise ConsentPolicyError(404,'Consent approval intent missing')
                if job['state']=='DELIVERED':return job['request_id']
                cipher=bytes(job['payload'])
                try:body=json.loads(self.crypto.decrypt(cipher[:12],cipher[12:],identifier.encode()))
                except Exception:raise ConsentPolicyError(503,'Consent approval intent cannot be verified') from None
                token=await service_token()
                try:subject=jwt.decode(token,options={'verify_signature':False}).get('sub')
                except Exception:raise ConsentPolicyError(503,'Consent approval service identity unavailable') from None
                if subject!=self.subject:raise ConsentPolicyError(503,'Consent approval service identity differs')
                result=await call(token,'POST','/v1/awe/requests',body=body,headers={'Idempotency-Key':'cm-partner-'+identifier})
                request_id=result.get('request_id') if isinstance(result,dict) else None
                if not isinstance(request_id,str) or not request_id:raise ConsentPolicyError(502,'Approval response missing request_id')
                with self.engine.begin() as c:
                    c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('karnatakadbt-native-consent-policy',0))"))
                    policy=c.execute(text('SELECT awe_request_id FROM public.partner_policies WHERE id=:id FOR UPDATE'),{'id':identifier}).first()
                    if policy is None or policy[0] not in {None,request_id}:raise ConsentPolicyError(409,'Consent policy approval binding differs')
                    c.execute(text('UPDATE public.partner_policies SET awe_request_id=:request,updated_at=now() WHERE id=:id'),{'request':request_id,'id':identifier})
                    c.execute(text("UPDATE kdbt_consent_delivery.jobs SET state='DELIVERED',request_id=:request WHERE policy_id=:id"),{'request':request_id,'id':identifier})
                return request_id
            finally:lock.execute(text('SELECT pg_advisory_unlock(hashtextextended(:key,0))'),{'key':key})
    async def recover(self,service_token,call,*,limit=50):
        if type(limit) is not int or not 1<=limit<=100:raise ValueError('Bounded delivery recovery required')
        with self.engine.connect() as c:identifiers=list(c.execute(text("SELECT policy_id FROM kdbt_consent_delivery.jobs WHERE state='PENDING' ORDER BY policy_id LIMIT :limit"),{'limit':limit}).scalars())
        for identifier in identifiers:await self.deliver(identifier,service_token,call)
        return {'delivered':len(identifiers)}
