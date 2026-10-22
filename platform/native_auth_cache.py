"""Native encrypted session storage with a data-only Java wire compatibility codec.

The optional codec reads/writes serialized DTO data without a JVM, application
JARs, Java class loading or execution. Expiry-preserving Redis CAS prevents a
handoff from reviving a consumed or concurrently changed transaction.
"""
import base64,copy,hashlib,hmac,json,secrets,struct,time
from pathlib import Path
import javaobj
from javaobj.v1.beans import JavaObject,JavaClass,JavaString,JavaArray,JavaEnum
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class AuthenticationFailure(Exception):
 def __init__(self,code='invalid_transaction'):self.code=code;super().__init__(code)

def b64(value):return base64.urlsafe_b64encode(value).decode().rstrip('=')
def unb64(value):
 try:return base64.b64decode(value+'='*(-len(value)%4),altchars=b'-_',validate=True)
 except (ValueError,TypeError):raise AuthenticationFailure('invalid_request') from None
def sha(value):return b64(hashlib.sha3_256(value.encode()).digest())
def canonical(value):return json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()

def plain(value,depth=0):
 if depth>30:raise AuthenticationFailure()
 if value is None or isinstance(value,(bool,int,float)):return value
 if isinstance(value,str):return str(value)
 if isinstance(value,dict):return {str(k):plain(v,depth+1) for k,v in value.items()}
 if isinstance(value,(list,set,tuple)):return [plain(v,depth+1) for v in value]
 if isinstance(value,JavaEnum):return str(value.constant)
 if isinstance(value,JavaObject):
  if value.classdesc.name in {'java.lang.Boolean','java.lang.Integer','java.lang.Long','java.lang.Float','java.lang.Double'}:return value.value
  fields=[];desc=value.classdesc
  while desc:fields+=desc.fields_names;desc=desc.superclass
  return {str(k):plain(getattr(value,k),depth+1) for k in fields if k not in {'linkCodeQueue'}}
 raise AuthenticationFailure('invalid_session_format')

def descriptor(name,uid,fields=(),types=(),flags=2,parent=None):
 value=JavaClass();value.name=name;value.serialVersionUID=uid;value.flags=flags
 value.fields_names=list(fields);value.fields_types=[JavaString(v) for v in types];value.superclass=parent
 return value

def jlist(items):
 value=JavaObject();value.classdesc=descriptor('java.util.ArrayList',8683452581122892189,['size'],['I'],3);value.size=len(items)
 value.annotations=[struct.pack('>i',len(items)).decode('latin1')]+[java(v) for v in items];return value
def jset(items):
 value=JavaObject();value.classdesc=descriptor('java.util.HashSet',-5024744406713321676,flags=3)
 value.annotations=[struct.pack('>ifi',16,.75,len(items)).decode('latin1')]+[java(v) for v in items];return value
def jmap(items):
 value=JavaObject();value.classdesc=descriptor('java.util.HashMap',362498820763181265,['loadFactor','threshold'],['F','I'],3);value.loadFactor=.75;value.threshold=12
 value.annotations=[struct.pack('>ii',16,len(items)).decode('latin1')]
 for k,v in items.items():value.annotations.extend([JavaString(k),java(v)])
 return value
def java(value):
 if value is None or isinstance(value,JavaObject):return value
 if isinstance(value,str):return JavaString(value)
 if isinstance(value,dict):return jmap(value)
 if isinstance(value,(list,tuple)):return jlist(value)
 if isinstance(value,set):return jset(sorted(value))
 if isinstance(value,bool):
  obj=JavaObject();obj.classdesc=descriptor('java.lang.Boolean',-3665804199014368530,['value'],['Z']);obj.value=value;return obj
 if isinstance(value,int):
  obj=JavaObject();obj.classdesc=descriptor('java.lang.Integer',1360826667806852920,['value'],['I'],parent=descriptor('java.lang.Number',-8742448824652078965));obj.value=value;return obj
 raise AuthenticationFailure('invalid_session_value')

class JavaSessionCodec:
 def __init__(self,templates):
  self.templates={name:javaobj.loads(base64.b64decode(value)) for name,value in templates.items()}
  if 'vci' not in self.templates:
   value=JavaObject();value.classdesc=descriptor('io.mosip.esignet.core.dto.vci.VCIssuanceTransaction',-1655569255547982560,
       ['cNonceExpireSeconds','cNonceIssuedEpoch','cNonce'],['I','J','Ljava/lang/String;'])
   value.cNonceExpireSeconds=0;value.cNonceIssuedEpoch=0;value.cNonce=None
   self.templates['vci']=value
  self.descriptors={}
  def walk(v,seen):
   if id(v) in seen:return
   seen.add(id(v))
   if isinstance(v,JavaObject):
    self.descriptors[v.classdesc.name]=v.classdesc
    for k,x in v.__dict__.items():
     if k!='classdesc':walk(x,seen)
   elif isinstance(v,dict):
    for k,x in v.items():walk(k,seen);walk(x,seen)
   elif isinstance(v,(list,tuple,set)):
    for x in v:walk(x,seen)
  for v in self.templates.values():walk(v,set())
 def decode(self,raw):
  if not isinstance(raw,bytes) or not 4<=len(raw)<=1024*1024 or not raw.startswith(b'\xac\xed\x00\x05'):raise AuthenticationFailure('invalid_session_format')
  try:
   obj=javaobj.loads(raw);value=plain(obj);value['_wire']=base64.b64encode(raw).decode()
   if hasattr(obj,'linkCodeQueue') and obj.linkCodeQueue is not None:
    queue=obj.linkCodeQueue;items=queue.items
    value['_queue']=[str(items[(queue.takeIndex+i)%len(items)]) for i in range(queue.count)]
   return value
  except (ValueError,TypeError,IndexError,KeyError,AttributeError):raise AuthenticationFailure('invalid_session_format') from None
 def typed(self,value,kind):
  if value is None:return False if kind=='Z' else None
  if kind in ['Ljava/util/List;','Ljava/util/Collection;']:return jlist(value)
  if kind=='Ljava/util/Set;':return jset(value)
  if kind.startswith('[L'):
   desc=self.descriptors.get(kind.replace('/','.'))
   if desc is None and kind=='[Ljava/lang/String;':desc=descriptor('[Ljava.lang.String;',-5921575005990323385)
   if desc is None:raise AuthenticationFailure('missing_session_descriptor')
   result=JavaArray(desc);result.extend(JavaString(v) for v in value);return result
  if kind.endswith('/ConsentAction;'):
   enum=JavaEnum(JavaString(value));enum.classdesc=descriptor('io.mosip.esignet.api.util.ConsentAction',0,flags=18,parent=descriptor('java.lang.Enum',0,flags=18));return enum
  if kind=='Lio/mosip/esignet/api/dto/Claims;':
   result=JavaObject();result.classdesc=self.descriptors['io.mosip.esignet.api.dto.Claims'];result.id_token=self.claim_map(value.get('id_token',{}));result.userinfo=self.claim_map(value.get('userinfo',{}));return result
  if kind=='Lio/mosip/esignet/core/dto/ProofKeyCodeExchange;':
   result=JavaObject();result.classdesc=self.descriptors.get('io.mosip.esignet.core.dto.ProofKeyCodeExchange')
   if result.classdesc is None:raise AuthenticationFailure('missing_pkce_descriptor')
   for n,t in zip(result.classdesc.fields_names,result.classdesc.fields_types):setattr(result,n,self.typed(value.get(n),str(t)))
   return result
  if kind in ['J','I','Z','F','D']:return value
  return java(value)
 def claim_map(self,claims):
  converted={}
  for name,v in claims.items():
   if not isinstance(v,dict):raise AuthenticationFailure('invalid_claims')
   obj=JavaObject();obj.classdesc=self.descriptors.get('io.mosip.esignet.api.dto.ClaimDetail')
   if obj.classdesc is None:raise AuthenticationFailure('missing_claim_descriptor')
   for field,kind in zip(obj.classdesc.fields_names,obj.classdesc.fields_types):setattr(obj,field,self.typed(v.get(field),str(kind)))
   converted[name]=obj
  return jmap(converted)
 def encode(self,value,template='transaction',rebuild_fields=()):
  try:
   result=javaobj.loads(base64.b64decode(value['_wire'])) if value.get('_wire') else copy.deepcopy(self.templates[template])
   if '_queue' in value and hasattr(result,'linkCodeQueue'):
    queue=result.linkCodeQueue;items=queue.items;values=value['_queue']
    if len(values)>len(items):raise AuthenticationFailure('invalid_link_queue')
    for i in range(len(items)):items[i]=JavaString(values[i]) if i<len(values) else None
    queue.count=len(values);queue.takeIndex=0;queue.putIndex=len(values)%len(items)
   for name,kind in zip(result.classdesc.fields_names,result.classdesc.fields_types):
    if name=='linkCodeQueue':continue
    item=value.get(name)
    if item is None and str(kind) in ['J','I']:item=0
    if name not in rebuild_fields and plain(getattr(result,name))==item:continue
    setattr(result,name,self.typed(item,str(kind)))
   return javaobj.dumps(result)
  except (ValueError,TypeError,IndexError,KeyError,AttributeError):raise AuthenticationFailure('session_encoding_failed') from None

class TransactionSecret:
 PREFIX='KDBTCACHE1.'
 def __init__(self,key):
  if len(key)!=32:raise ValueError('AES-256 session key required')
  self.aead=AESGCM(key)
 def encrypt(self,value):
  nonce=secrets.token_bytes(12);return self.PREFIX+b64(nonce+self.aead.encrypt(nonce,value.encode(),b'OIDC_SERVICE/TRANSACTION_CACHE/native-v1'))
 def decrypt(self,value):
  try:
   if not value.startswith(self.PREFIX):raise ValueError()
   raw=unb64(value[len(self.PREFIX):]);return self.aead.decrypt(raw[:12],raw[12:],b'OIDC_SERVICE/TRANSACTION_CACHE/native-v1').decode()
  except Exception:raise AuthenticationFailure('invalid_session_ciphertext') from None

class SessionCache:
 def __init__(self,redis,codec,ttls):self.redis,self.codec,self.ttls=redis,codec,ttls
 def key(self,kind,identifier):return (kind+'::'+identifier).encode()
 def get(self,kind,identifier,required=True):
  key=self.key(kind,identifier);raw=self.redis.get(key)
  if raw is None:
   if required:raise AuthenticationFailure()
   return None
  if self.redis.pttl(key)<=0:raise AuthenticationFailure()
  return self.codec.decode(raw)
 def put(self,kind,identifier,value,*,template='transaction',ttl=None):
  raw=self.codec.encode(value,template);milliseconds=int((ttl if ttl is not None else self.ttls[kind])*1000)
  if not 0<milliseconds<=86400000:raise AuthenticationFailure('invalid_session_ttl')
  self.redis.set(self.key(kind,identifier),raw,px=milliseconds)
 def move(self,old,new,identifier,value,*,new_identifier=None):
  oldkey=self.key(old,identifier);newkey=self.key(new,new_identifier or identifier)
  before=base64.b64decode(value['_wire']) if value.get('_wire') else self.redis.get(oldkey)
  if before is None:raise AuthenticationFailure()
  # Stage transitions use the configured next-stage lifetime, matching the
  # protocol. Restarts and handoffs never call this operation or extend TTLs.
  raw=self.codec.encode(value);ttl=int(self.ttls[new]*1000)
  result=self.redis.eval("if redis.call('GET',KEYS[1])~=ARGV[1] then return 0 end redis.call('SET',KEYS[2],ARGV[2],'PX',ARGV[3]);redis.call('DEL',KEYS[1]);return 1",2,oldkey,newkey,before,raw,ttl)
  if result!=1:raise AuthenticationFailure()
 def delete(self,kind,identifier):self.redis.delete(self.key(kind,identifier))
 def update(self,kind,identifier,value,*,template='transaction'):
  if not value.get('_wire'):raise AuthenticationFailure('missing_session_version')
  before=base64.b64decode(value['_wire']);raw=self.codec.encode(value,template)
  result=self.redis.eval("if redis.call('GET',KEYS[1])~=ARGV[1] then return 0 end redis.call('SET',KEYS[1],ARGV[2],'XX','KEEPTTL');return 1",1,self.key(kind,identifier),before,raw)
  if result!=1:raise AuthenticationFailure()
