"""Authenticated native cache envelopes and expiry-preserving CAS migration.

Caller supplies an approved legacy codec; this module never imports HSM keys.
Migration does not extend expiry or overwrite concurrent session changes.
"""
import base64,json,secrets,time
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

class CacheFailure(Exception):pass
class CacheCipher:
 PREFIX=b'KDBTCACHE1:'
 def __init__(self,key,kid):
  if len(key)!=32 or not kid or len(kid)>128:raise ValueError('AES-256 key and bounded key ID required')
  self.aead=AESGCM(key);self.kid=kid
 def encrypt(self,value,scope):
  if not isinstance(value,bytes) or not isinstance(scope,bytes) or not scope:raise CacheFailure('Byte payload and cache-key scope required')
  nonce=secrets.token_bytes(12);head=json.dumps({'v':1,'kid':self.kid},sort_keys=True,separators=(',',':')).encode()
  encrypted=self.aead.encrypt(nonce,value,head+b'\x00'+scope)
  return self.PREFIX+base64.urlsafe_b64encode(head)+b'.'+base64.urlsafe_b64encode(nonce+encrypted)
 def decrypt(self,value,scope):
  try:
   if not value.startswith(self.PREFIX):raise ValueError()
   header,body=value[len(self.PREFIX):].split(b'.');head=base64.b64decode(header,altchars=b'-_',validate=True);meta=json.loads(head)
   if meta!={'v':1,'kid':self.kid}:raise ValueError()
   raw=base64.b64decode(body,altchars=b'-_',validate=True)
   return self.aead.decrypt(raw[:12],raw[12:],head+b'\x00'+scope)
  except (ValueError,TypeError,InvalidTag,KeyError):raise CacheFailure('Invalid cache envelope or scope')

# Redis TIME makes expiry checking independent of client clock skew. DUMP/RESTORE
# is deliberately not used: recovery always retains the existing absolute expiry.
SNAPSHOT="""local v=redis.call('GET',KEYS[1]); if not v then return {} end
local ttl=redis.call('PTTL',KEYS[1]); local t=redis.call('TIME');
local now=t[1]*1000+math.floor(t[2]/1000); return {v,ttl,now}"""
CAS="""local old=redis.call('GET',KEYS[1]); if not old then return -2 end
if old~=ARGV[1] then return 0 end
local ttl=redis.call('PTTL',KEYS[1]); if ttl<0 then return -3 end
local t=redis.call('TIME'); local now=t[1]*1000+math.floor(t[2]/1000);
local remaining=tonumber(ARGV[3])-now; if remaining<=0 then return -2 end
if remaining>ttl then remaining=ttl end
redis.call('SET',KEYS[1],ARGV[2],'PX',remaining); return 1"""
def snapshot(client,key):
 result=client.eval(SNAPSHOT,1,key)
 if not result:return None
 value,ttl,now=result
 if ttl<0:raise CacheFailure('Session without bounded expiry requires explicit review')
 return {'value':value,'expires_ms':now+ttl}
def replace(client,key,before,new_value):
 return int(client.eval(CAS,1,key,before['value'],new_value,before['expires_ms']))
def migrate(client,key,cipher,legacy_decode):
 before=snapshot(client,key)
 if before is None:return 'EXPIRED'
 if before['value'].startswith(cipher.PREFIX):
  cipher.decrypt(before['value'],key);return 'ALREADY_NATIVE'
 payload=legacy_decode(before['value']);value=cipher.encrypt(payload,key)
 status=replace(client,key,before,value)
 return {1:'MIGRATED',0:'CONCURRENT_CHANGE',-2:'EXPIRED',-3:'UNBOUNDED_EXPIRY'}[status]
def rollback(client,key,cipher,legacy_encode):
 before=snapshot(client,key)
 if before is None:return 'EXPIRED'
 if not before['value'].startswith(cipher.PREFIX):return 'ALREADY_LEGACY'
 payload=cipher.decrypt(before['value'],key);value=legacy_encode(payload)
 status=replace(client,key,before,value)
 return {1:'ROLLED_BACK',0:'CONCURRENT_CHANGE',-2:'EXPIRED',-3:'UNBOUNDED_EXPIRY'}[status]
