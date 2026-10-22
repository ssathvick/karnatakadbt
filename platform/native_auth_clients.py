"""Native OIDC client registry and pinned administrative authorization."""
import datetime,json,secrets
from urllib.parse import urlsplit
import httpx,jwt,psycopg2
from native_auth_cache import AuthenticationFailure,canonical

def strings(value,maximum=30,allow_empty=False):
 if not isinstance(value,list) or (not value and not allow_empty) or len(value)>maximum or any(not isinstance(v,str) or not v or len(v)>2048 or ',' in v for v in value):raise AuthenticationFailure('invalid_request')
 return list(dict.fromkeys(value))

def public_keys(value):
 if not isinstance(value,dict):raise AuthenticationFailure('invalid_public_key')
 keys=value.get('keys',[value])
 if not isinstance(keys,list) or not 1<=len(keys)<=5:raise AuthenticationFailure('invalid_public_key')
 seen=set()
 for key in keys:
  if not isinstance(key,dict) or any(k in key for k in ['d','p','q','dp','dq','qi','oth','k']) or key.get('kty')!='RSA' or key.get('alg','RS256') not in ['RS256','PS256'] or any(k in key for k in ['jku','x5u']):raise AuthenticationFailure('invalid_public_key')
  try:public=jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
  except (ValueError,KeyError,TypeError):raise AuthenticationFailure('invalid_public_key') from None
  if public.key_size<2048 or key.get('kid') in seen:raise AuthenticationFailure('invalid_public_key')
  seen.add(key.get('kid'))
 return keys

class AdministrativeIdentity:
 def __init__(self,settings):
  self.settings=settings;self.keys=jwt.PyJWKClient(settings['jwks_uri'],timeout=5)
 def authorize(self,token,scopes=None):
  try:
   key=self.keys.get_signing_key_from_jwt(token).key
   value=jwt.decode(token,key,algorithms=['RS256'],issuer=self.settings['issuer'],options={'verify_aud':False,'require':['sub','iss','exp','iat']})
   if not set(scopes or [self.settings['required_scope']]) & set(value.get('scope','').split()):raise AuthenticationFailure('access_denied')
   return value
  except AuthenticationFailure:raise
  except Exception:raise AuthenticationFailure('invalid_token') from None

class ClientRegistry:
 def __init__(self,connection,cache=None):self.connection,self.cache=connection,cache
 def connect(self):return psycopg2.connect(**self.connection)
 def get(self,identifier,*,active=True):
  if not isinstance(identifier,str) or not 1<=len(identifier)<=100:raise AuthenticationFailure('invalid_client_id')
  with self.connect() as c,c.cursor() as q:
   q.execute('SELECT row_to_json(t) FROM esignet.client_detail t WHERE id=%s',(identifier,));row=q.fetchone()
  if row is None or active and row[0]['status']!='ACTIVE':raise AuthenticationFailure('invalid_client_id')
  r=row[0]
  def parts(v):return v.split(',') if v else []
  try:name=json.loads(r['name'])
  except (ValueError,TypeError):name={'@none':r['name']}
  return {'id':r['id'],'rpId':r['rp_id'],'name':name,'logoUri':r['logo_uri'],'redirectUris':parts(r['redirect_uris']),
   'claims':parts(r['claims']),'acrValues':parts(r['acr_values']),'grantTypes':parts(r['grant_types']),
   'clientAuthMethods':parts(r['auth_methods']),'publicKey':json.loads(r['public_key']),'status':r['status']}
 def validate(self,value,*,create):
  if not isinstance(value,dict):raise AuthenticationFailure('invalid_request')
  for name in ['clientName','logoUri']:
   if not isinstance(value.get(name),str) or len(value[name])>(2048 if name=='logoUri' else 256):raise AuthenticationFailure('invalid_request')
  logo=urlsplit(value['logoUri'])
  if logo.scheme not in ['https','http'] or not logo.netloc or logo.username or logo.password:raise AuthenticationFailure('invalid_logo_uri')
  redirects=strings(value.get('redirectUris'),5)
  for uri in redirects:
   parsed=urlsplit(uri)
   if parsed.fragment or parsed.username or parsed.password or parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ['127.0.0.1','localhost','::1']):raise AuthenticationFailure('invalid_redirect_uri')
  claims=strings(value.get('userClaims'),allow_empty=create);acrs=strings(value.get('authContextRefs'))
  grants=strings(value.get('grantTypes'),3);methods=strings(value.get('clientAuthMethods'),3)
  if set(grants)-{'authorization_code'} or set(methods)-{'private_key_jwt'}:raise AuthenticationFailure('invalid_request')
  names=value.get('clientNameLangMap') or {'@none':value['clientName']}
  if not isinstance(names,dict) or len(names)>30 or any(not isinstance(k,str) or not isinstance(v,str) or len(v)>256 for k,v in names.items()):raise AuthenticationFailure('invalid_client_name')
  name=canonical(names).decode()
  if len(name)>256:raise AuthenticationFailure('invalid_client_name')
  if create:public_keys(value.get('publicKey'))
  status=value.get('status','ACTIVE')
  if status not in ['ACTIVE','INACTIVE']:raise AuthenticationFailure('invalid_status')
  return {'name':name,'logo_uri':value['logoUri'],'redirect_uris':','.join(redirects),'claims':','.join(claims),'acr_values':','.join(acrs),'grant_types':','.join(grants),'auth_methods':','.join(methods),'status':status}
 def create(self,value,principal):
  row=self.validate(value,create=True);identifier=value.get('clientId') or secrets.token_urlsafe(32);rp=value.get('relyingPartyId') or principal.get('azp')
  if not isinstance(identifier,str) or not 1<=len(identifier)<=100 or not isinstance(rp,str) or not 1<=len(rp)<=100:raise AuthenticationFailure('invalid_client_id')
  try:
   with self.connect() as c,c.cursor() as q:
    q.execute('''INSERT INTO esignet.client_detail(id,name,rp_id,logo_uri,redirect_uris,claims,acr_values,public_key,grant_types,auth_methods,status,cr_dtimes)
VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(identifier,row['name'],rp,row['logo_uri'],row['redirect_uris'],row['claims'],row['acr_values'],canonical(value['publicKey']).decode(),row['grant_types'],row['auth_methods'],row['status'],datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)))
  except psycopg2.errors.UniqueViolation:raise AuthenticationFailure('duplicate_client_id') from None
  return {'clientId':identifier,'status':row['status']}
 def update(self,identifier,value,principal):
  self.get(identifier,active=False);row=self.validate(value,create=False)
  with self.connect() as c,c.cursor() as q:
   q.execute('''UPDATE esignet.client_detail SET name=%s,logo_uri=%s,redirect_uris=%s,claims=%s,acr_values=%s,grant_types=%s,auth_methods=%s,status=%s,upd_dtimes=%s WHERE id=%s''',
    (row['name'],row['logo_uri'],row['redirect_uris'],row['claims'],row['acr_values'],row['grant_types'],row['auth_methods'],row['status'],datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),identifier))
   if q.rowcount!=1:raise AuthenticationFailure('invalid_client_id')
  if self.cache:self.cache.delete('clientdetails',identifier)
  return {'clientId':identifier,'status':row['status']}
