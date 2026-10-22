"""Native linked-device authorization and signed consent transitions."""
import datetime,hmac,secrets,time,uuid
from native_auth_cache import AuthenticationFailure,sha

class LinkedAuthorization:
 def __init__(self,engine):self.engine=engine;self.cache=engine.cache
 def generate(self,value,headers):
  tx=self.engine.transaction('preauth',value.get('transactionId'),headers)
  if tx['currentLinkCodeLimit']>=self.engine.settings.get('link_code_limit',5):raise AuthenticationFailure('link_code_limit_reached')
  code=secrets.token_urlsafe(12);digest=sha(code);queue=tx.get('_queue',[])
  if len(queue)>=self.engine.settings.get('link_code_queue_size',3):self.cache.delete('linkcodegenerated',queue.pop(0))
  queue.append(digest);tx['_queue']=queue;tx['currentLinkCodeLimit']+=1
  self.cache.update('preauth',tx['transactionId'],tx)
  self.cache.put('linkcodegenerated',digest,{'transactionId':tx['transactionId'],'linkedTransactionId':None},template='link')
  expiry=datetime.datetime.fromtimestamp(self.engine.clock()+self.engine.settings['cache_ttls']['linkcodegenerated'],datetime.timezone.utc)
  return {'transactionId':tx['transactionId'],'linkCode':code,'expireDateTime':expiry.isoformat(timespec='milliseconds').replace('+00:00','Z')}
 def link(self,value,version=1):
  code=value.get('linkCode')
  if not isinstance(code,str) or len(code)>128:raise AuthenticationFailure('invalid_link_code')
  digest=sha(code);meta=self.cache.get('linkcodegenerated',digest);tx=self.engine.transaction('preauth',meta['transactionId'])
  linked=secrets.token_urlsafe(32);tx['linkedTransactionId']=linked;tx['linkedCodeHash']=digest;meta['linkedTransactionId']=linked
  # A code can link only once, and the browser's ordinary-login transaction
  # leaves preauthentication in the same atomic operation.
  oldmeta=self.cache.key('linkcodegenerated',digest);oldtx=self.cache.key('preauth',tx['transactionId'])
  import base64
  oldraw=base64.b64decode(meta['_wire']);oldtxraw=base64.b64decode(tx['_wire'])
  linkedraw=self.cache.codec.encode(tx);metaraw=self.cache.codec.encode(meta,'link')
  result=self.engine.redis.eval("if redis.call('GET',KEYS[1])~=ARGV[1] or redis.call('GET',KEYS[2])~=ARGV[2] then return 0 end redis.call('SET',KEYS[3],ARGV[3],'PX',ARGV[5]);redis.call('SET',KEYS[4],ARGV[4],'PX',ARGV[6]);redis.call('DEL',KEYS[1],KEYS[2]);return 1",4,
   oldmeta,oldtx,self.cache.key('linked',linked),self.cache.key('linkedcode',digest),oldraw,oldtxraw,linkedraw,metaraw,
   self.engine.settings['cache_ttls']['linked']*1000,self.engine.settings['cache_ttls']['linkedcode']*1000)
  if result!=1:raise AuthenticationFailure('invalid_link_code')
  client=self.engine.clients.get(tx['clientId']);acrs=tx['requestedClaims']['id_token']['acr']['values']
  response={'linkTransactionId':linked,'logoUrl':client['logoUri'],'authFactors':[self.engine.settings['acr_factors'][a] for a in acrs],
   'authorizeScopes':tx['requestedAuthorizeScopes'],'essentialClaims':tx['essentialClaims'],'voluntaryClaims':tx['voluntaryClaims'],'configs':self.engine.settings['ui_configs']}
  if version>=2:response.update(clientName=client['name'],credentialScopes=tx.get('requestedCredentialScopes',[]))
  return response
 def metadata(self,value):
  code=value.get('linkCode') or value.get('linkedCode');origin=value.get('transactionId')
  if not isinstance(code,str) or not isinstance(origin,str) or len(code)>128:raise AuthenticationFailure('invalid_link_code')
  digest=sha(code);meta=self.cache.get('linkedcode',digest,required=False) or self.cache.get('linkcodegenerated',digest,required=False)
  if not meta or not hmac.compare_digest(meta['transactionId'],origin):raise AuthenticationFailure('invalid_link_code')
  return digest,meta
 def status(self,value):
  digest,meta=self.metadata(value)
  return {'linkStatus':'LINKED'} if meta.get('linkedTransactionId') else None
 def consent(self,value,version=1):
  identifier=value.get('linkedTransactionId');tx=self.engine.transaction('linkedauth',identifier)
  self.engine.validate_consent(tx,value)
  if version>=2:
   self.engine.consent.save(tx,value.get('signature'))
  self.cache.move('linkedauth','consented',identifier,tx)
  return {'linkedTransactionId':identifier}
 def code(self,value):
  digest,meta=self.metadata(value);linked=meta.get('linkedTransactionId')
  if not linked:raise AuthenticationFailure('invalid_link_code')
  tx=self.cache.get('consented',linked,required=False)
  if tx is None:return None
  self.engine.clients.get(tx['clientId'])
  if tx.get('codeHash'):raise AuthenticationFailure('auth_code_already_issued')
  code=secrets.token_urlsafe(32);tx['codeHash']=sha(code)
  import base64
  original=base64.b64decode(tx['_wire']);encoded=self.cache.codec.encode(tx)
  result=self.engine.redis.eval("if redis.call('GET',KEYS[1])~=ARGV[1] then return 0 end local ttl=redis.call('PTTL',KEYS[1]);if ttl<=0 then return 0 end redis.call('SET',KEYS[1],ARGV[2],'PX',ttl);redis.call('SET',KEYS[2],ARGV[2],'PX',ARGV[3]);return 1",2,
   self.cache.key('consented',linked),self.cache.key('authcodegenerated',tx['codeHash']),original,encoded,self.engine.settings['cache_ttls']['authcodegenerated']*1000)
  if result!=1:raise AuthenticationFailure('auth_code_already_issued')
  return {'nonce':tx.get('nonce'),'state':tx.get('state'),'code':code,'redirectUri':tx['redirectUri']}
