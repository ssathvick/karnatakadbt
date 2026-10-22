"""Checkpointed import of a complete retained credential cache snapshot.

Does not grant ownership or change routing. Pending offers/codes and issuance
nonces are imported together; unknown/orphan bindings are never guessed.
"""
import base64,hashlib,io,json,math,re,secrets,struct,time
from pathlib import Path
from native_certify_cache_projection import BUSINESS_CACHES,ProjectionBlocked,import_transaction
from native_certify_recovery_wire import javaobj
from native_auth_cache import plain

def canonical(value):
 return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def decode_snapshot(frame,*,with_deadlines=False,live_at=None):
 if live_at is not None and (not isinstance(live_at,(int,float)) or not math.isfinite(live_at) or live_at<=0):raise ProjectionBlocked('Valid cache observation time required')
 if not isinstance(frame,bytes) or not 1<=len(frame)<=32*1024*1024:raise ProjectionBlocked('Bounded authenticated cache frame required')
 stream=io.BytesIO(frame)
 def read(length):
  value=stream.read(length)
  if len(value)!=length:raise ProjectionBlocked('Truncated cache frame')
  return value
 def integer():return struct.unpack('>i',read(4))[0]
 def text():
  try:return read(struct.unpack('>H',read(2))[0]).decode('ascii')
  except UnicodeDecodeError:raise ProjectionBlocked('ASCII cache name required') from None
 version=text()
 if version not in {'KDBT-CERTIFY-CACHE-V1','KDBT-CERTIFY-CACHE-V2'}:raise ProjectionBlocked('Unknown cache frame version')
 count=integer()
 if not 0<=count<=1000:raise ProjectionBlocked('Cache count bound exceeded')
 caches={};deadlines={};total=0
 for _ in range(count):
  name=text();entries=integer();total+=entries
  if not re.fullmatch('[A-Za-z0-9_.:-]{1,128}',name) or name in caches or not 0<=entries<=100000 or total>100000:raise ProjectionBlocked('Invalid cache framing')
  values={};expiry={};seen=set()
  for _ in range(entries):
   records=[]
   for _ in range(2):
    size=integer()
    if not 0<size<=1024*1024:raise ProjectionBlocked('Serialized record size bound exceeded')
    records.append(read(size))
   try:key=javaobj.loads(records[0])
   except Exception:raise ProjectionBlocked('Invalid serialized cache key') from None
   if not isinstance(key,str) or not 1<=len(key)<=4096 or key in seen:raise ProjectionBlocked('Unique bounded string cache key required')
   seen.add(key)
   deadline=struct.unpack('>q',read(8))[0] if version.endswith('V2') else None
   if deadline is not None and not 0<=deadline<=32503680000000:raise ProjectionBlocked('Invalid absolute cache expiry')
   if live_at is None or deadline in {None,0} or deadline>live_at*1000:
    values[str(key)]=records[1];expiry[str(key)]=deadline
  caches[name]=values;deadlines[name]=expiry
 if stream.read(1):raise ProjectionBlocked('Trailing cache frame data')
 if not set(BUSINESS_CACHES)<=set(caches):raise ProjectionBlocked('Complete business cache set required')
 # Preserve every namespace for the coordinator's coverage check. This parser
 # must never discard an unfamiliar nonempty cache as if it were migrated.
 return (caches,deadlines) if with_deadlines else caches

def equivalent_snapshots(expected,observed,*,at=None):
 at=time.time() if at is None else at
 before,expiry=decode_snapshot(expected,with_deadlines=True,live_at=at)
 after,current=decode_snapshot(observed,with_deadlines=True,live_at=at)
 if before!=after:return False
 for name,values in expiry.items():
  for key,deadline in values.items():
   other=current[name][key]
   if deadline is None or other is None:
    if deadline!=other:return False
   elif (deadline==0)!=(other==0) or abs(deadline-other)>2:return False
 return True

def decode(wire,name,value):
 if not isinstance(value,bytes) or not 4<=len(value)<=1024*1024:raise ProjectionBlocked('Bounded retained DTO required')
 try:
  obj=javaobj.loads(value);expected=wire.templates[name].classdesc
  if obj.classdesc.name!=expected.name or obj.classdesc.serialVersionUID!=expected.serialVersionUID:raise ProjectionBlocked('Unrecognized retained DTO')
  result=plain(obj)
  if not isinstance(result,dict):raise ProjectionBlocked('Retained DTO object required')
  return result
 except (ValueError,TypeError,KeyError,AttributeError,RecursionError,IndexError):raise ProjectionBlocked('Invalid retained cache DTO') from None

class PendingCacheImport:
 def __init__(self,folder,authorization,wire,*,fenced):
  self.folder=Path(folder).resolve(strict=True)
  root=Path('/opt/karnatakadbt/private/mosip-migration/remaining-three')
  if not self.folder.is_relative_to(root) or self.folder.stat().st_uid!=0 or self.folder.stat().st_mode&0o077:raise ProjectionBlocked('Private recovery checkpoint required')
  self.authorization,self.wire,self.fenced=authorization,wire,fenced
  self.path=self.folder/'pending-cache-import.json'
 def require(self):
  if self.fenced() is not True:raise ProjectionBlocked('Observed closed producer and worker fences required')
 def save(self,value):
  import os
  temporary=self.folder/('cache-import-'+secrets.token_hex(10)+'.pending')
  with temporary.open('xb') as stream:
   os.chmod(temporary,0o600);stream.write(canonical(value));stream.flush();os.fsync(stream.fileno())
  os.replace(temporary,self.path)
  fd=os.open(self.folder,os.O_DIRECTORY|os.O_RDONLY)
  try:os.fsync(fd)
  finally:os.close(fd)
 def prepare(self,caches,*,issuer,snapshot_time,reconcile_absent_codes=False,cache_deadlines=None):
  self.require()
  if set(caches)!=set(BUSINESS_CACHES) or issuer!=self.authorization.configuration.settings['issuer'] or not math.isfinite(snapshot_time):raise ProjectionBlocked('Complete pinned cache snapshot required')
  if sum(len(v) for v in caches.values())>100000:raise ProjectionBlocked('Snapshot count bound exceeded')
  if cache_deadlines is not None:
   if set(cache_deadlines)!=set(caches) or any(set(cache_deadlines[name])!=set(caches[name]) for name in caches):raise ProjectionBlocked('Complete cache expiry inventory required')
   if any(type(value) is not int or value<0 for values in cache_deadlines.values() for value in values.values()):raise ProjectionBlocked('Authenticated absolute cache expiry required')
  def cache_expiry(name,key):
   value=cache_deadlines[name][key] if cache_deadlines is not None else 0
   return value/1000 if value else math.inf
  size=0;fingerprint={}
  for cache,values in caches.items():
   fingerprint[cache]={}
   for key,value in values.items():
    if not isinstance(key,str) or not 1<=len(key)<=4096 or not isinstance(value,bytes):raise ProjectionBlocked('Bounded string cache key and serialized value required')
    size+=len(key.encode())+len(value)
    if size>32*1024*1024:raise ProjectionBlocked('Snapshot byte bound exceeded')
    fingerprint[cache][key]=hashlib.sha256(value).hexdigest()
  if type(reconcile_absent_codes) is not bool:raise ProjectionBlocked('Explicit absent-code reconciliation policy required')
  binding_body={'caches':fingerprint,'issuer':issuer,'snapshot_time':snapshot_time}
  if cache_deadlines is not None:binding_body['cache_deadlines']=cache_deadlines
  if reconcile_absent_codes:binding_body['reconcile_absent_codes']=True
  binding=hashlib.sha256(canonical(binding_body)).hexdigest()
  if self.path.exists():
   if self.path.is_symlink() or self.path.stat().st_uid!=0 or self.path.stat().st_mode&0o077:raise ProjectionBlocked('Unsafe cache checkpoint')
   state=json.loads(self.path.read_bytes())
   if state['source_sha256']!=binding:raise ProjectionBlocked('Authoritative cache snapshot changed')
   return state
  offers={};codes={};sessions=[];expired=0;configurations={}
  def configuration(identifier):
   result=self.authorization.active_configuration(identifier)
   configurations[identifier]=hashlib.sha256(json.dumps(result,sort_keys=True,default=str).encode()).hexdigest()
   return result
  for key,serialized in caches['credentialOfferCache'].items():
   if not key.startswith('credential_offer:') or len(key)<=len('credential_offer:'):raise ProjectionBlocked('Canonical retained offer cache key required')
   key=key[len('credential_offer:'):]
   value=decode(self.wire,'offer',serialized)
   try:
    grant=value['grants']['preAuthorizedCode'];code=grant['preAuthorizedCode'];configs=value['credentialConfigurationIds']
    if value['credentialIssuer']!=issuer or not isinstance(code,str) or not 1<=len(code)<=4096 or not isinstance(configs,list) or len(configs)!=1 or not isinstance(configs[0],str):raise ValueError()
    if code in offers:raise ValueError()
    offers[code]={'key':key,'configuration':configs[0],'tx':grant.get('txCode')}
   except (ValueError,TypeError,KeyError):raise ProjectionBlocked('Ambiguous retained offer binding') from None
  for cache_key,serialized in caches['preAuthCodeCache'].items():
   if not cache_key.startswith('pre_auth_code:') or len(cache_key)<=len('pre_auth_code:'):raise ProjectionBlocked('Canonical retained code cache key required')
   code=cache_key[len('pre_auth_code:'):]
   value=decode(self.wire,'code',serialized)
   try:
    expiry=value['expiresAt'];created=value['createdAt'];claims=value['claims'];config=value['credentialConfigurationId'];tx=value.get('txnCode')
    if type(expiry) is not int or type(created) is not int or expiry<=10**12 or created<=0 or not isinstance(claims,dict) or len(canonical(claims))>512*1024:raise ValueError()
    # Native SQL stores epoch seconds in bigint. Round down before binding SQL
    # so PostgreSQL cannot round a fractional cache deadline into extra time.
    expiry=math.floor(min(expiry/1000,cache_expiry('preAuthCodeCache',cache_key)));created=created//1000 if created>10**12 else created
    if created>snapshot_time+30 or expiry<=created or expiry-snapshot_time>86400:raise ValueError()
    if tx is not None and (not isinstance(tx,str) or not 1<=len(tx)<=128):raise ValueError()
    configured=configuration(config)
    offer=offers.get(code)
    if offer and offer['configuration']!=config:raise ValueError()
    details=offer['tx'] if offer else None
    if details is not None and (details.get('length')!=len(tx or '') or details.get('inputMode') not in ['numeric','text']):raise ValueError()
    if details and details['inputMode']=='numeric' and not tx.isdigit():raise ValueError()
    if expiry<=snapshot_time:expired+=1;continue
    identifier=hashlib.sha256(code.encode()).hexdigest();salt=secrets.token_bytes(32)
    payload={'configuration':config,'scope':configured['scope'],'claims':claims,'code':code,'offer':offer['key'] if offer else None,
      'created_at':created,'tx_code':tx,'tx_length':len(tx or ''),'tx_mode':details['inputMode'] if details else 'numeric' if tx and tx.isdigit() else 'text'}
    codes[identifier]={'id':identifier,'offer_hash':hashlib.sha256(offer['key'].encode()).hexdigest() if offer else None,
      'kind':'PREAUTH','content':base64.b64encode(self.authorization.seal(payload,identifier)).decode(),'expires_at':expiry,
      'tx_salt':base64.b64encode(salt).decode(),'tx_hash':base64.b64encode(hashlib.pbkdf2_hmac('sha256',tx.encode(),salt,600000)).decode() if tx else None}
   except (ValueError,TypeError,KeyError,AttributeError):raise ProjectionBlocked('Invalid retained preauthorization state') from None
  absent=set(offers)-{k[len('pre_auth_code:'):] for k in caches['preAuthCodeCache']}
  if absent and not reconcile_absent_codes:raise ProjectionBlocked('Orphan retained offers require consumption reconciliation')
  denied=[]
  for code in sorted(absent):
   offer=offers[code];configuration(offer['configuration'])
   denied.append({'id':hashlib.sha256(code.encode()).hexdigest(),'offer_hash':hashlib.sha256(offer['key'].encode()).hexdigest(),
     'configuration':offer['configuration']})
  for token_hash,serialized in caches['vcissuance'].items():
   value=decode(self.wire,'transaction',serialized)
   try:
    configured=configuration(value['credentialConfigurationId'])
    if not isinstance(value['claims'],dict) or len(canonical(value['claims']))>512*1024:raise ValueError()
    expiry=math.floor(min(value['cNonceIssuedEpoch']+value['cNonceExpireSeconds'],cache_expiry('vcissuance',token_hash)))
    if expiry<=snapshot_time:expired+=1;continue
    identifier,payload,expiry=import_transaction(self.wire,serialized,token_hash,configuration=configured,now=snapshot_time,observed_expires_at=expiry)
    sessions.append({'id':identifier,'content':base64.b64encode(self.authorization.seal(payload,identifier)).decode(),'expires_at':expiry})
   except (ValueError,TypeError,KeyError):raise ProjectionBlocked('Invalid retained credential nonce state') from None
  state={'version':1,'phase':'PREPARED','source_sha256':binding,'authorizations':list(codes.values()),'sessions':sessions,'expired_entries':expired,'configuration_sha256':configurations}
  if reconcile_absent_codes:state.update(absent_codes=denied,denied_at=int(snapshot_time))
  self.require();self.save(state);return state
 def apply(self,state,*,connection,scope=None,source=None,destination=None):
  from psycopg2.extensions import TRANSACTION_STATUS_IDLE
  if connection.get_transaction_status()!=TRANSACTION_STATUS_IDLE:raise ProjectionBlocked('Dedicated idle destination transaction required')
  try:return self._apply(state,connection=connection,scope=scope,source=source,destination=destination)
  except BaseException:
   try:connection.rollback()
   except Exception:pass # SQL_INTENT remains durable if the commit ACK was lost.
   raise
 def _apply(self,state,*,connection,scope=None,source=None,destination=None):
  self.require()
  actual=json.loads(self.path.read_bytes())
  if actual!=state or actual['phase'] not in {'PREPARED','SQL_INTENT','COMPLETE'}:raise ProjectionBlocked('Exact durable checkpoint required')
  if not connection.info.dbname.startswith(('kdbt_original_','kdbt_transfer_')):
   from native_remaining_three_projection_scope import ProductionProjectionScope
   if not isinstance(scope,ProductionProjectionScope) or not source or not destination or source['dbname']!='inji_certify' or not destination['dbname'].startswith('kdbt_native_certify_'):raise ProjectionBlocked('Pinned production projection scope required')
   scope.authorize(source,destination,'certify')
   if connection.info.dbname!=destination['dbname'] or connection.info.host!=destination['host'] or connection.info.user!=destination['user']:raise ProjectionBlocked('Projection connection differs')
  with connection.cursor() as cursor:
   cursor.execute("SET LOCAL lock_timeout='5s'")
   cursor.execute('LOCK TABLE certify.credential_config IN SHARE MODE')
   for identifier,fingerprint in state['configuration_sha256'].items():
    configured=self.authorization.active_configuration(identifier)
    if hashlib.sha256(json.dumps(configured,sort_keys=True,default=str).encode()).hexdigest()!=fingerprint:raise ProjectionBlocked('Credential configuration changed after export')
   cursor.execute('LOCK TABLE certify.native_authorization,certify.native_credential_session IN SHARE ROW EXCLUSIVE MODE')
   for plan in state.get('absent_codes',[]):
    cursor.execute('SELECT kind,offer_hash,content,used_at FROM certify.native_authorization WHERE id=%s FOR UPDATE',(plan['id'],))
    existing=cursor.fetchone()
    if existing:
     payload=self.authorization.open(existing[2],plan['id'])
     if (existing[0]!='PREAUTH' or existing[1]!=plan['offer_hash'] or payload.get('configuration')!=plan['configuration']
         or hashlib.sha256(payload.get('code','').encode()).hexdigest()!=plan['id']):
      raise ProjectionBlocked('Absent legacy code conflicts with native authorization binding')
     # Absence does not identify whether the original code was consumed,
     # expired or evicted. Preserve denial, never guess an active grant.
     # Existing consumption time, failed attempts and expiry are untouched.
     cursor.execute('UPDATE certify.native_authorization SET used_at=coalesce(used_at,%s) WHERE id=%s',(state['denied_at'],plan['id']))
   for table,plans in [('native_authorization',state['authorizations']),('native_credential_session',state['sessions'])]:
    for plan in plans:
     if plan['expires_at']<=time.time() and state['phase']!='COMPLETE':raise ProjectionBlocked('Pending state expired before commit')
     columns=list(plan);values=[base64.b64decode(plan[k]) if k in {'content','tx_salt','tx_hash'} and plan[k] is not None else plan[k] for k in columns]
     cursor.execute('SELECT '+','.join(columns)+' FROM certify.'+table+' WHERE id=%s',(plan['id'],));existing=cursor.fetchone()
     if existing:
      if [bytes(v) if isinstance(v,memoryview) else v for v in existing]!=values:raise ProjectionBlocked('Existing native changes cannot be overwritten')
      if table=='native_authorization':
       cursor.execute('SELECT used_at,attempts FROM certify.native_authorization WHERE id=%s',(plan['id'],))
       used,attempts=cursor.fetchone()
       if used is not None or attempts:raise ProjectionBlocked('Consumed code or failed attempts cannot be revived')
     else:
      if state['phase']=='COMPLETE':raise ProjectionBlocked('Previously imported state is missing')
      cursor.execute('INSERT INTO certify.'+table+'('+','.join(columns)+') VALUES('+','.join(['%s']*len(columns))+')',values)
   self.require()
   if scope:scope.require()
   self.save({**state,'phase':'SQL_INTENT'})
  connection.commit();state={**state,'phase':'COMPLETE'};self.save(state);return state
