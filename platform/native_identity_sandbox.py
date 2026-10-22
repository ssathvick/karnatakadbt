"""Native synthetic identity/KYC replacement candidate.

This is a test identity provider, never an Aadhaar authenticator. It contains no
MOSIP imports, never calls a legacy service, and requires separate administration
and service credentials. Signing-key cutover is deliberately external to this
module: a candidate key does not become a production trust anchor by deployment.
"""
import base64,datetime,hashlib,hmac,json,secrets,sqlite3,threading,time,unicodedata,uuid
import os
from pathlib import Path
import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00','Z')
def b64(value):return base64.urlsafe_b64encode(value).decode().rstrip('=')
def unb64(value):return base64.urlsafe_b64decode(value+'='*(-len(value)%4))
def norm(value):return unicodedata.normalize('NFC',str(value))
class IdentityFailure(Exception):
 def __init__(self,code):self.code=code

class NativeIdentitySandbox:
 def __init__(self,settings,signer,*,clock=time.time):
  if settings.get('environment')!='synthetic-only' or settings.get('aadhaar_enabled') is not False:raise ValueError('Explicit synthetic-only configuration required')
  self.settings,self.signer,self.clock=settings,signer,clock;self.path=Path(settings['database']);self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
  self.key=unb64(settings['data_key'])
  if len(self.key)!=32:raise ValueError('AES-256 data key required')
  self.aead=AESGCM(self.key);self.ttl=int(settings.get('transaction_ttl',60));self.max_attempts=int(settings.get('max_attempts',5));self.lock=threading.RLock()
  if not 1<=self.ttl<=600 or not 1<=self.max_attempts<=10:raise ValueError('Bounded identity challenge policy required')
  with self.connect() as c:c.executescript('''PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS identities(reference TEXT PRIMARY KEY,content BLOB NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS challenges(reference TEXT NOT NULL,rp TEXT NOT NULL,client TEXT NOT NULL,transaction_id TEXT NOT NULL,proof BLOB NOT NULL,expires REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,consumed INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(reference,rp,client,transaction_id));
CREATE TABLE IF NOT EXISTS exchanges(token TEXT PRIMARY KEY,reference TEXT NOT NULL,rp TEXT NOT NULL,client TEXT NOT NULL,transaction_id TEXT NOT NULL,subject TEXT NOT NULL,issued REAL NOT NULL,expires REAL NOT NULL,consumed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS wallet_proof_replay(proof_hash TEXT PRIMARY KEY,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS control(id INTEGER PRIMARY KEY CHECK(id=1),owner TEXT NOT NULL);
INSERT OR IGNORE INTO control VALUES(1,'CANDIDATE');''')
  self.path.chmod(0o600)
 def connect(self):
  c=sqlite3.connect(self.path,timeout=15);c.row_factory=sqlite3.Row;return c
 def reference(self,individual):return hmac.new(self.key,b'identity:'+individual.encode(),hashlib.sha256).hexdigest()
 def seal(self,value,aad):
  iv=secrets.token_bytes(12);return iv+self.aead.encrypt(iv,json.dumps(value,ensure_ascii=False,separators=(',',':')).encode(),aad.encode())
 def open(self,value,aad):return json.loads(self.aead.decrypt(value[:12],value[12:],aad.encode()))
 def validate_identity(self,value):
  if not isinstance(value,dict):raise IdentityFailure('invalid_identity')
  if 'passwordCredential' in value:raise IdentityFailure('invalid_identity')
  if 'password' in value and (not isinstance(value['password'],str) or not 8<=len(value['password'])<=30):raise IdentityFailure('invalid_identity')
  required=['individualId','pin','encodedPhoto','individualBiometrics']
  if any(not isinstance(value.get(k),str) or (k!='encodedPhoto' and not value[k]) or len(value[k])>(512*1024 if k=='encodedPhoto' else 8192) for k in required if k!='individualBiometrics'):raise IdentityFailure('invalid_identity')
  for k in ['dateOfBirth','email','phone','postalCode','zoneInfo','locale']:
   if value.get(k) is not None and (not isinstance(value[k],str) or not value[k] or len(value[k])>8192):raise IdentityFailure('invalid_identity')
  for key in ['name','fullName','givenName','familyName','middleName','nickName','preferredUsername','gender','streetAddress','locality','region','country']:
   if key not in value or value[key] is None:continue
   items=value[key]
   if not isinstance(items,list) or not items or len(items)>30 or any(not isinstance(v,dict) or not isinstance(v.get('language'),str) or not isinstance(v.get('value'),str) or len(v['value'])>8192 for v in items):raise IdentityFailure('invalid_identity')
  bio=value['individualBiometrics']
  if not isinstance(bio,dict) or not all(k in bio for k in ['format','version','value']) or not isinstance(bio['value'],str):raise IdentityFailure('invalid_identity')
  if len(json.dumps(value))>512*1024:raise IdentityFailure('invalid_identity')
 def add(self,value):
  self.validate_identity(value);value=dict(value);ref=self.reference(value['individualId'])
  if 'password' in value:
   salt=secrets.token_bytes(16)
   proof=hashlib.scrypt(value.pop('password').encode(),salt=salt,n=16384,r=8,p=1,dklen=32)
   value['passwordCredential']={'algorithm':'scrypt-v1','salt':b64(salt),'hash':b64(proof)}
  try:
   with self.connect() as c:c.execute('INSERT INTO identities VALUES(?,?,?)',(ref,self.seal(value,ref),self.clock()))
  except sqlite3.IntegrityError:raise IdentityFailure('duplicate_individual_id')
  return {'status':'ACTIVE'}
 def identity(self,individual):
  if not isinstance(individual,str) or not individual or len(individual)>8192:raise IdentityFailure('invalid_individual_id')
  ref=self.reference(individual)
  with self.connect() as c:r=c.execute('SELECT content FROM identities WHERE reference=?',(ref,)).fetchone()
  if not r:raise IdentityFailure('invalid_individual_id')
  return self.open(r['content'],ref)
 def scope(self,rp,client):
  authorize=self.settings.get('client_authorizer')
  if callable(authorize):
   if not authorize(rp,client):raise IdentityFailure('invalid_client')
  elif {'relying_party':rp,'client':client} not in self.settings['allowed_clients']:raise IdentityFailure('invalid_client')
 def otp(self,rp,client,value):
  self.scope(rp,client);identity=self.identity(value.get('individualId'));transaction=value.get('transactionId');channels=value.get('otpChannels')
  if not isinstance(transaction,str) or not transaction or len(transaction)>256:raise IdentityFailure('invalid_transaction_id')
  if not isinstance(channels,list) or not channels or any(v not in ['email','phone','mobile'] for v in channels):raise IdentityFailure('invalid_otp_channel')
  email=identity.get('email','');phone=identity.get('phone','');masked_email=masked_phone=None
  if 'email' in channels and email:
   prefix,suffix=email.split('@',1);masked_email=''.join(ch if (i+1)%3==0 else 'X' for i,ch in enumerate(prefix))+'@'+suffix
  if any(v in channels for v in ['phone','mobile']) and phone:masked_phone='X'*(len(phone)//2+1)+phone[len(phone)//2+1:]
  if not masked_email and not masked_phone:raise IdentityFailure('no_email_mobile_found')
  # Fixed values are allowed only in this explicitly synthetic, authenticated
  # service. No SMS/email delivery and no Aadhaar validation are claimed.
  proof=self.settings.get('synthetic_otp')
  if not isinstance(proof,str) or len(proof)<6:raise IdentityFailure('synthetic_otp_not_configured')
  ref=self.reference(identity['individualId']);digest=hmac.new(self.key,('otp:'+rp+':'+client+':'+transaction+':'+proof).encode(),hashlib.sha256).digest()
  with self.connect() as c:
   c.execute('BEGIN IMMEDIATE');previous=c.execute('SELECT expires FROM challenges WHERE reference=? AND rp=? AND client=? AND transaction_id=?',(ref,rp,client,transaction)).fetchone()
   if previous and previous['expires']>self.clock():raise IdentityFailure('transaction_already_exists')
   c.execute('INSERT OR REPLACE INTO challenges VALUES(?,?,?,?,?,?,0,0)',(ref,rp,client,transaction,digest,self.clock()+self.ttl))
  return {'transactionId':transaction,'maskedEmail':masked_email,'maskedMobile':masked_phone}
 def auth(self,rp,client,value):
  self.scope(rp,client);identity=self.identity(value.get('individualId'));ref=self.reference(identity['individualId']);transaction=value.get('transactionId')
  if not isinstance(transaction,str) or not transaction or len(transaction)>256:raise IdentityFailure('invalid_transaction_id')
  factors=[k for k in ['otp','pin','password','biometrics','kba','tokens'] if value.get(k) is not None]
  if not factors:raise IdentityFailure('auth_failed')
  with self.lock,self.connect() as c:
   c.execute('BEGIN IMMEDIATE')
   for factor in factors:
    if factor=='otp':
     challenge=c.execute('SELECT * FROM challenges WHERE reference=? AND rp=? AND client=? AND transaction_id=?',(ref,rp,client,transaction)).fetchone()
     if not challenge or challenge['consumed'] or challenge['expires']<self.clock() or challenge['attempts']>=self.max_attempts:raise IdentityFailure('invalid_transaction')
     expected=hmac.new(self.key,('otp:'+rp+':'+client+':'+transaction+':'+str(value['otp'])).encode(),hashlib.sha256).digest()
     if not hmac.compare_digest(expected,challenge['proof']):
      c.execute('UPDATE challenges SET attempts=attempts+1 WHERE reference=? AND rp=? AND client=? AND transaction_id=?',(ref,rp,client,transaction));c.commit();raise IdentityFailure('auth_failed')
     c.execute('UPDATE challenges SET consumed=1 WHERE reference=? AND rp=? AND client=? AND transaction_id=?',(ref,rp,client,transaction))
    elif factor=='pin':
     if not isinstance(value['pin'],str) or not hmac.compare_digest(value['pin'].encode(),identity['pin'].encode()):raise IdentityFailure('auth_failed')
    elif factor=='password':
     password=value['password'];credential=identity.get('passwordCredential')
     if not isinstance(password,str) or not 8<=len(password)<=30 or not isinstance(credential,dict) or set(credential)!={'algorithm','salt','hash'} or credential.get('algorithm')!='scrypt-v1':raise IdentityFailure('auth_failed')
     try:salt,expected=unb64(credential['salt']),unb64(credential['hash'])
     except (ValueError,TypeError):raise IdentityFailure('auth_failed')
     if len(salt)!=16 or len(expected)!=32:raise IdentityFailure('auth_failed')
     actual=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1,dklen=32)
     if not hmac.compare_digest(actual,expected):raise IdentityFailure('auth_failed')
    elif factor=='biometrics':
     # Synthetic biometric fixture matching only; never a real matcher.
     if not isinstance(value['biometrics'],str) or not hmac.compare_digest(value['biometrics'].encode(),identity['individualBiometrics']['value'].encode()):raise IdentityFailure('auth_failed')
    elif factor=='kba':
     try:challenge=json.loads(unb64(value['kba']))
     except (ValueError,TypeError):raise IdentityFailure('auth_failed')
     allowed=self.settings.get('kba_fields',['dateOfBirth','email','phone'])
     if not isinstance(challenge,dict) or not challenge or any(k not in allowed for k in challenge):raise IdentityFailure('auth_failed')
     for key,text in challenge.items():
      actual=identity.get(key)
      if isinstance(actual,list):actual=next((x['value'] for x in actual if x['language']==self.settings.get('default_language','eng')),None)
      if actual is None or not hmac.compare_digest(norm(actual).encode(),norm(text).encode()):raise IdentityFailure('auth_failed')
    elif factor=='tokens':
     # Original mock accepted arbitrary nonempty strings. A native replacement
     # accepts only specifically provisioned synthetic fixtures, never a forgery.
     approved=self.settings.get('synthetic_tokens',{}).get(ref,[])
     verifier=self.settings.get('wallet_token_verifier')
     if not isinstance(value['tokens'],list) or not 1<=len(value['tokens'])<=5:raise IdentityFailure('auth_failed')
     for token in value['tokens']:
      if not isinstance(token,str):raise IdentityFailure('auth_failed')
      if any(hmac.compare_digest(token,known) for known in approved):continue
      if not callable(verifier) or not verifier(identity['individualId'],token):raise IdentityFailure('auth_failed')
      digest=hashlib.sha256(token.encode()).hexdigest()
      try:
       expires=jwt.decode(token,options={'verify_signature':False})['exp']
       c.execute('DELETE FROM wallet_proof_replay WHERE expires<?',(self.clock(),))
       c.execute('INSERT INTO wallet_proof_replay VALUES(?,?)',(digest,expires))
      except (sqlite3.IntegrityError,KeyError,ValueError,TypeError):raise IdentityFailure('auth_failed')
   token=b64(secrets.token_bytes(32));subject=b64(hashlib.sha3_256((identity['individualId']+rp).encode()).digest());issued=self.clock()
   c.execute('INSERT INTO exchanges VALUES(?,?,?,?,?,?,?,?,0)',(token,ref,rp,client,transaction,subject,issued,issued+self.ttl))
  return {'authStatus':True,'kycToken':token,'partnerSpecificUserToken':subject}
 def claims(self,identity,requested,locales):
  if not isinstance(requested,list) or not all(isinstance(k,str) for k in requested) or len(requested)>40:raise IdentityFailure('invalid_claims')
  locales=locales or [self.settings.get('default_language','eng')]
  if not isinstance(locales,list) or not all(isinstance(k,str) for k in locales) or len(locales)>30:raise IdentityFailure('invalid_claims')
  result={};mapping={'name':'name','given_name':'givenName','family_name':'familyName','middle_name':'middleName','nickname':'nickName','preferred_username':'preferredUsername','gender':'gender','birthdate':'dateOfBirth','email':'email','phone_number':'phone','zoneinfo':'zoneInfo','locale':'locale','picture':'encodedPhoto','individual_id':'individualId'}
  def local(out,claim,value):
   if isinstance(value,list):
    for locale in locales:
     item=next((v['value'] for v in value if v['language'].casefold()==locale.casefold() or v['language'].casefold().startswith(locale.casefold())),None)
     if item is not None:out[claim if len(locales)==1 else claim+'#'+locale]=item
   elif value is not None:out[claim]=value
  for claim in requested:
   if claim=='address':
    address={}
    for out,key in [('street_address','streetAddress'),('locality','locality'),('region','region'),('country','country'),('postal_code','postalCode')]:local(address,out,identity.get(key))
    result['address']=address
   elif claim in mapping:local(result,claim,(identity.get('name') or identity.get('fullName')) if claim=='name' else identity.get(mapping[claim]))
  return result
 def exchange(self,rp,client,value):
  self.scope(rp,client);ref=self.reference(value.get('individualId',''));token=value.get('kycToken');transaction=value.get('transactionId')
  with self.lock,self.connect() as c:
   c.execute('BEGIN IMMEDIATE');entry=c.execute('SELECT * FROM exchanges WHERE token=? AND reference=? AND rp=? AND client=? AND transaction_id=?',(token,ref,rp,client,transaction)).fetchone()
   if not entry or entry['consumed']:raise IdentityFailure('mock-ida-006')
   if self.clock()>entry['expires']:raise IdentityFailure('mock-ida-007')
   try:
    wire_time=value['requestDateTime']
    if isinstance(wire_time,list):
     if len(wire_time) not in {6,7} or any(type(v) is not int for v in wire_time):raise ValueError()
     if len(wire_time)==7 and not 0<=wire_time[6]<1000000000:raise ValueError()
     requested_time=datetime.datetime(*wire_time[:6],microsecond=wire_time[6]//1000 if len(wire_time)==7 else 0,tzinfo=datetime.timezone.utc)
    else:requested_time=datetime.datetime.fromisoformat(wire_time.replace('Z','+00:00'))
    requested=(requested_time if requested_time.tzinfo else requested_time.replace(tzinfo=datetime.timezone.utc)).timestamp()
   except (ValueError,KeyError,TypeError):raise IdentityFailure('invalid_request_time')
   if requested<entry['issued']-1 or requested>self.clock()+30:raise IdentityFailure('invalid_request_time')
   claims=self.claims(self.identity(value['individualId']),value.get('acceptedClaims'),value.get('claimLocales'));claims['sub']=entry['subject']
   signed=self.signer(claims);c.execute('UPDATE exchanges SET consumed=1 WHERE token=?',(token,))
  return {'kyc':signed}

def build(settings,signer):
 if settings.get('enforce_ownership') and settings.get('authority_owner') not in {'CANDIDATE','NATIVE'}:raise ValueError('Explicit matching identity authority owner required')
 store=NativeIdentitySandbox(settings,signer);app=FastAPI(title='KarnatakaDBT native synthetic identity candidate',docs_url=None,redoc_url=None);app.state.store=store
 def envelope(value=None,error=None):return {'responseTime':now(),'response':value,'errors':[] if not error else [{'errorCode':error,'message':error}]}
 @app.middleware('http')
 async def access(request,call_next):
  if request.url.path in {'/health','/v1/mock-identity-system/actuator/health','/v1/mock-identity-system/v3/api-docs'}:return await call_next(request)
  expected=settings['administration_token'] if request.method=='POST' and request.url.path.endswith('/identity') else settings['service_token']
  supplied=request.headers.get('Authorization','').removeprefix('Bearer ')
  if not supplied or not hmac.compare_digest(supplied,expected):return JSONResponse(envelope(error='access_denied'),status_code=401)
  if request.method=='POST' and settings.get('enforce_ownership'):
   with store.connect() as c:owner=c.execute('SELECT owner FROM control WHERE id=1').fetchone()[0]
   if owner!=settings['authority_owner']:return JSONResponse(envelope(error='writer_fenced'),status_code=503)
  data=bytearray()
  async for chunk in request.stream():
   data.extend(chunk)
   if len(data)>1024*1024:return JSONResponse(envelope(error='request_too_large'),status_code=413)
  request._body=bytes(data)
  response=await call_next(request);response.headers['Cache-Control']='no-store';response.headers['X-KarnatakaDBT-Identity-Backend']='native-authority' if settings.get('authority_backend') else 'native-candidate'
  # The retained Java caller otherwise reuses dead pooled sockets after a
  # controlled authority restart. Persist sessions in the store, not a TCP link.
  response.headers['Connection']='close';return response
 @app.exception_handler(IdentityFailure)
 async def failure(request,error):return JSONResponse(envelope(error=error.code))
 async def object_body(request):
  try:value=await request.json()
  except (ValueError,TypeError):raise IdentityFailure('invalid_request')
  if not isinstance(value,dict):raise IdentityFailure('invalid_request')
  return value
 @app.get('/health')
 def health():
  with store.connect() as c:owner=c.execute('SELECT owner FROM control WHERE id=1').fetchone()[0];count=c.execute('SELECT count(*) FROM identities').fetchone()[0]
  return {'ready':True,'owner':owner,'identity_count':count,'synthetic_only':True,'aadhaar_enabled':False,'legacy_http_dependency':False,'production_key_cutover_verified':owner=='NATIVE' and bool(settings.get('production_signing_verified'))}
 @app.post('/v1/mock-identity-system/identity')
 async def create(request:Request):return envelope(store.add((await object_body(request)).get('request')))
 @app.get('/v1/mock-identity-system/identity/{individual}')
 def read(individual:str):return envelope(store.identity(individual))
 @app.post('/v1/mock-identity-system/send-otp/{rp}/{client}')
 async def send(rp:str,client:str,request:Request):return envelope(store.otp(rp,client,await object_body(request)))
 @app.post('/v1/mock-identity-system/kyc-auth/{rp}/{client}')
 async def authenticate(rp:str,client:str,request:Request):return envelope(store.auth(rp,client,await object_body(request)))
 @app.post('/v1/mock-identity-system/kyc-exchange/{rp}/{client}')
 async def exchange(rp:str,client:str,request:Request):return envelope(store.exchange(rp,client,await object_body(request)))
 return app

if os.environ.get('KDBT_NATIVE_IDENTITY_SETTINGS'):
 settings=json.loads(Path(os.environ['KDBT_NATIVE_IDENTITY_SETTINGS']).read_text())
 key=unb64(settings['data_key']);sealed=Path(settings['candidate_signing_key']).read_bytes();pem=AESGCM(key).decrypt(sealed[:12],sealed[12:],b'native-identity-candidate-signing-key')
 signing=serialization.load_pem_private_key(pem,password=None)
 app=build(settings,lambda payload:jwt.encode(payload,signing,algorithm='RS256',headers={'kid':settings['candidate_signing_kid']}))
