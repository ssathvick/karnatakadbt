"""Native authorization, authentication, consent and token state machine.

All protocol state is persisted before a response is returned. Registered
redirects, per-transaction bindings, PKCE, client assertions and replay checks
are enforced independently of the browser UI.
"""
import base64,copy,datetime,hashlib,hmac,json,re,secrets,time
from urllib.parse import quote
import httpx,jwt
from native_auth_cache import AuthenticationFailure,SessionCache,TransactionSecret,b64,unb64,sha,canonical
from native_auth_clients import ClientRegistry,public_keys
from native_auth_signing import NativeSigningAuthority
from native_auth_consent import NativeConsent

def bounded(value,maximum=8192,*,empty=False):
 if not isinstance(value,str) or len(value)>maximum or (not value and not empty):raise AuthenticationFailure('invalid_request')
 return value
def allowed_list(value,allowed,*,required=()):
 if not isinstance(value,list) or len(value)>100 or any(not isinstance(v,str) for v in value) or set(value)-set(allowed) or set(required)-set(value):raise AuthenticationFailure('invalid_consent')
 return list(dict.fromkeys(value))

class NativeAuthorization:
 def __init__(self,settings,redis,codec,*,transport=None,clock=time.time):
  self.settings,self.redis,self.clock=settings,redis,clock;self.cache=SessionCache(redis,codec,settings['cache_ttls'])
  self.clients=ClientRegistry(settings['connection'],self.cache);self.signing=NativeSigningAuthority(settings['signing'])
  self.cipher=TransactionSecret(base64.b64decode(settings['cache_key']));self.transport=transport
  self.binding=None;self.credentials=None;self.consent=NativeConsent(self)
 def identity(self,operation,transaction,value):
  path=operation+'/'+quote(transaction['relyingPartyId'],safe='')+'/'+quote(transaction['clientId'],safe='')
  with httpx.Client(trust_env=False,timeout=15,transport=self.transport) as h:
   r=h.post(self.settings['identity_origin']+'/v1/mock-identity-system/'+path,json=value,headers={'Authorization':'Bearer '+self.settings['identity_service_token']})
   try:body=r.json()
   except ValueError:raise AuthenticationFailure('identity_service_unavailable') from None
   if r.status_code!=200 or body.get('errors'):
    code=next((v.get('errorCode') for v in body.get('errors',[]) or []),'identity_service_unavailable')
    raise AuthenticationFailure(code if code in {'invalid_individual_id','invalid_transaction','auth_failed','no_email_mobile_found','invalid_otp_channel'} else 'auth_failed')
   return body['response']
 def binding_headers(self,transaction,headers):
  key=headers.get('oauth-details-key','');digest=headers.get('oauth-details-hash','')
  if not key or not digest or not hmac.compare_digest(key,transaction['transactionId']) or not hmac.compare_digest(digest,transaction['oauthDetailsHash']):raise AuthenticationFailure()
 def transaction(self,kind,identifier,headers=None):
  value=self.cache.get(kind,bounded(identifier,256));self.clients.get(value['clientId'])
  if headers is not None:self.binding_headers(value,headers)
  return value
 def details(self,value,version=1):
  client=self.clients.get(value.get('clientId'));redirect=value.get('redirectUri')
  if redirect not in client['redirectUris']:raise AuthenticationFailure('invalid_redirect_uri')
  if value.get('responseType','code')!='code':raise AuthenticationFailure('unsupported_response_type')
  if value.get('display','page') not in self.settings['discovery'].get('display_values_supported',['page']):raise AuthenticationFailure('invalid_display')
  if value.get('prompt') is not None and any(v not in ['none','login','consent','select_account'] for v in value['prompt'].split()):raise AuthenticationFailure('invalid_prompt')
  if value.get('maxAge') is not None and (type(value['maxAge']) is not int or value['maxAge']<0):raise AuthenticationFailure('invalid_max_age')
  scope=bounded(value.get('scope',''),2048,empty=True).split();supported=set(self.settings['openid_scopes'])|set(self.settings['authorize_scopes'])|set(self.settings['credential_scopes'])|{'openid'}
  if set(scope)-supported:raise AuthenticationFailure('invalid_scope')
  requested=copy.deepcopy(value.get('claims') or {})
  if not isinstance(requested,dict) or set(requested)-{'userinfo','id_token'}:raise AuthenticationFailure('invalid_claims')
  essential=[];voluntary=[]
  for where in ['userinfo','id_token']:
   mapping=requested.get(where) or {}
   if not isinstance(mapping,dict):raise AuthenticationFailure('invalid_claims')
   for name,detail in mapping.items():
    if where=='id_token' and name=='acr':continue
    if name not in client['claims'] or name not in self.settings['claims_supported']:raise AuthenticationFailure('invalid_claims')
    if detail is None:detail={};mapping[name]=detail
    if not isinstance(detail,dict) or set(detail)-{'essential','value','values'} or type(detail.get('essential',False)) is not bool:raise AuthenticationFailure('invalid_claims')
    if detail.get('value') is not None and not isinstance(detail['value'],str):raise AuthenticationFailure('invalid_claims')
    if detail.get('values') is not None and (not isinstance(detail['values'],list) or any(not isinstance(v,str) for v in detail['values']) or len(detail['values'])>30):raise AuthenticationFailure('invalid_claims')
    (essential if detail.get('essential') else voluntary).append(name)
  if not requested.get('userinfo') and 'openid' in scope:
   optional=[name for group in scope for name in self.settings['scope_claims'].get(group,[]) if name in client['claims']]
   requested['userinfo']={name:{} for name in optional};voluntary+=optional
  acrs=bounded(value.get('acrValues') or ' '.join(client['acrValues']),1024).split()
  requested_acr=(requested.get('id_token') or {}).get('acr')
  if requested_acr:
   if not isinstance(requested_acr,dict):raise AuthenticationFailure('invalid_acr')
   selected=requested_acr.get('values') or ([requested_acr['value']] if requested_acr.get('value') else acrs)
   if not isinstance(selected,list) or any(not isinstance(v,str) for v in selected):raise AuthenticationFailure('invalid_acr')
   acrs=selected
  if not acrs or set(acrs)-set(client['acrValues']) or any(v not in self.settings['acr_factors'] for v in acrs):raise AuthenticationFailure('invalid_acr')
  requested.setdefault('id_token',{})['acr']={'essential':True,'value':None,'values':acrs}
  factors=[copy.deepcopy(self.settings['acr_factors'][acr]) for acr in acrs]
  transaction=secrets.token_urlsafe(32);names=client['name']
  config=copy.deepcopy(self.settings['ui_configs'])
  if self.settings['environment']=='CANDIDATE':
   device=self.settings.get('candidate_device_origins',{}).get(client['id'])
   if device:config['sbi.device.base-url']=device
  response={'transactionId':transaction,'logoUrl':client['logoUri'],'authFactors':factors,
   'authorizeScopes':[v for v in scope if v in self.settings['authorize_scopes']],
   'essentialClaims':list(dict.fromkeys(essential)),'voluntaryClaims':list(dict.fromkeys(v for v in voluntary if v not in essential)),
   'configs':config,'redirectUri':redirect}
  if version>=2:response.update(clientName=names,credentialScopes=[v for v in scope if v in self.settings['credential_scopes']])
  proof=None
  if value.get('codeChallenge') or value.get('codeChallengeMethod'):
   if version<2 or value.get('codeChallengeMethod')!='S256' or not re.fullmatch('[A-Za-z0-9_-]{43}',value.get('codeChallenge','')):raise AuthenticationFailure('invalid_code_challenge')
   proof={'codeChallenge':value['codeChallenge'],'codeChallengeMethod':'S256'}
  state=value.get('state');nonce=value.get('nonce')
  for item in [state,nonce]:
   if item is not None:bounded(item,2048)
  detailhash=b64(hashlib.sha256(canonical(response)).digest())
  record={'transactionId':transaction,'clientId':client['id'],'relyingPartyId':client['rpId'],'redirectUri':redirect,'requestedClaims':requested,
   'essentialClaims':response['essentialClaims'],'voluntaryClaims':response['voluntaryClaims'],'requestedAuthorizeScopes':response['authorizeScopes'],
   'requestedCredentialScopes':[v for v in scope if v in self.settings['credential_scopes']], 'claimsLocales':(value.get('claimsLocales') or '').split(),
   'authTransactionId':''.join(secrets.choice('0123456789') for _ in range(10)),'nonce':nonce,'state':state,'oauthDetailsHash':detailhash,
   'currentLinkCodeLimit':0,'proofKeyCodeExchange':proof,'authTimeInSeconds':0}
  self.cache.put('preauth',transaction,record);return response
 def rate(self,individual,operation):
  identifier=sha(individual);blocked=self.redis.get(('blocked::'+identifier).encode())
  if blocked:raise AuthenticationFailure('blocked')
  key='kdbt-native-auth-rate::'+identifier+':'+operation
  count=self.redis.eval("local n=redis.call('INCR',KEYS[1]);if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end;return n",1,key,self.settings.get('rate_window',60))
  if count>self.settings.get('rate_limit',10):raise AuthenticationFailure('too_many_requests')
 def send_otp(self,value,headers=None,linked=False):
  kind='linked' if linked else 'preauth';tx=self.transaction(kind,value.get('transactionId'),None if linked else headers)
  individual=bounded(value.get('individualId'));channels=value.get('otpChannels')
  if not isinstance(channels,list) or not channels or set(channels)-{'email','phone','mobile'}:raise AuthenticationFailure('invalid_otp_channel')
  self.rate(individual,'otp');result=self.identity('send-otp',tx,{'individualId':individual,'transactionId':tx['authTransactionId'],'otpChannels':channels})
  result['transactionId']=value['transactionId'];return result
 def authenticate(self,value,headers=None,*,linked=False,version=1):
  identifier=value.get('linkedTransactionId') if linked else value.get('transactionId');kind='linked' if linked else 'preauth'
  tx=self.transaction(kind,identifier,None if linked else headers);individual=bounded(value.get('individualId'));self.rate(individual,'authentication')
  challenges=value.get('challengeList')
  if not isinstance(challenges,list) or not 1<=len(challenges)<=5:raise AuthenticationFailure('invalid_auth_challenge')
  accepted={};formats={}
  for challenge in challenges:
   if not isinstance(challenge,dict) or set(challenge)-{'authFactorType','challenge','format'}:raise AuthenticationFailure('invalid_auth_challenge')
   factor=challenge.get('authFactorType');body=bounded(challenge.get('challenge'),32768)
   if factor not in ['PIN','PWD','OTP','BIO','KBA','WLA'] or factor in accepted:raise AuthenticationFailure('invalid_auth_factor')
   formats[factor]=challenge.get('format')
   if formats[factor]!={'PIN':'number','PWD':'alpha-numeric','OTP':'alpha-numeric','BIO':'encoded-json','KBA':'base64-json','WLA':'jwt'}[factor]:raise AuthenticationFailure('invalid_auth_factor_type_or_challenge_format')
   if factor=='PWD' and not 8<=len(body)<=30:raise AuthenticationFailure('invalid_auth_challenge')
   accepted[factor]=body
  client=self.clients.get(tx['clientId']);requested_acrs=tx['requestedClaims']['id_token']['acr']['values']
  possibilities=[self.settings['acr_factors'][v] for v in requested_acrs if v in client['acrValues'] and v in self.settings['acr_factors']]
  if not any({f['type'] for f in group}<=set(accepted) for group in possibilities):raise AuthenticationFailure('invalid_auth_factor')
  provider={'individualId':individual,'transactionId':tx['authTransactionId']}
  mapping={'PIN':'pin','PWD':'password','OTP':'otp','BIO':'biometrics','KBA':'kba'}
  if 'WLA' in accepted:
   if self.binding is None:raise AuthenticationFailure('wallet_not_configured')
   provider.update(self.binding.validate_challenge(individual,accepted['WLA'],tx))
  for factor,name in mapping.items():
   if factor in accepted:provider[name]=accepted[factor]
  result=self.identity('kyc-auth',tx,provider)
  if result.get('authStatus') is not True:raise AuthenticationFailure('auth_failed')
  tx.update(individualId=self.cipher.encrypt(individual),individualIdHash=sha(individual),kycToken=result['kycToken'],partnerSpecificUserToken=result['partnerSpecificUserToken'],
   providedAuthFactors=[[v] for v in accepted],authTimeInSeconds=int(self.clock()))
  if version>=2:tx['consentAction']=self.consent.action(tx,linked=linked)
  new='linkedauth' if linked else 'authenticated';self.cache.move(kind,new,identifier,tx)
  response={'linkedTransactionId' if linked else 'transactionId':identifier}
  if version>=2:response['consentAction']=tx['consentAction']
  return response
 def validate_consent(self,tx,value):
  tx['acceptedClaims']=allowed_list(value.get('acceptedClaims') or [],tx['essentialClaims']+tx['voluntaryClaims'],required=tx['essentialClaims'])
  tx['permittedScopes']=allowed_list(value.get('permittedAuthorizeScopes') or [],tx['requestedAuthorizeScopes']+tx.get('requestedCredentialScopes',[]))
 def code(self,value,headers):
  tx=self.transaction('authenticated',value.get('transactionId'),headers);self.validate_consent(tx,value)
  code=secrets.token_urlsafe(32);tx['codeHash']=sha(code)
  self.cache.move('authenticated','authcodegenerated',tx['transactionId'],tx,new_identifier=tx['codeHash'])
  return {'nonce':tx.get('nonce'),'state':tx.get('state'),'code':code,'redirectUri':tx['redirectUri']}
 def client_assertion(self,form,client):
  if form.get('client_assertion_type')!='urn:ietf:params:oauth:client-assertion-type:jwt-bearer':raise AuthenticationFailure('invalid_client')
  assertion=bounded(form.get('client_assertion'),16384)
  try:
   header=jwt.get_unverified_header(assertion)
   if header.get('alg')!='RS256' or header.get('crit'):raise ValueError()
   keys=public_keys(client['publicKey']);matches=[v for v in keys if v.get('kid')==header.get('kid')]
   if len(matches)!=1:raise ValueError()
   claims=jwt.decode(assertion,jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(matches[0])),algorithms=['RS256'],issuer=client['id'],subject=client['id'],
    audience=self.settings['token_audiences'],options={'require':['iss','sub','aud','exp','iat','jti']},leeway=5)
   now=self.clock()
   if claims['exp']-claims['iat']>300 or claims['iat']>now+5 or not isinstance(claims['jti'],str) or len(claims['jti'])>256:raise ValueError()
  except AuthenticationFailure:raise
  except Exception:raise AuthenticationFailure('invalid_client') from None
  key='kdbt-native-client-assertion::'+sha(client['id']+':'+claims['jti'])
  if not self.redis.set(key,'consumed',nx=True,ex=max(1,int(claims['exp']-now+5))):raise AuthenticationFailure('invalid_client')
 def exchange(self,tx):
  individual=self.cipher.decrypt(tx['individualId'])
  payload={'individualId':individual,'transactionId':tx['authTransactionId'],'kycToken':tx['kycToken'],
   'requestDateTime':datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'),
   'acceptedClaims':tx['acceptedClaims'],'claimLocales':tx['claimsLocales']}
  value=self.identity('kyc-exchange',tx,payload);signed=bounded(value.get('kyc'),1024*1024)
  try:
   header=jwt.get_unverified_header(signed)
   if header.get('alg')!='RS256':raise ValueError()
   keys=self.settings['identity_verification_keys'];matched=[]
   for key in keys:
    try:matched.append(jwt.decode(signed,key,algorithms=['RS256'],options={'verify_aud':False,'require':['sub']}))
    except jwt.PyJWTError:pass
   if len(matched)!=1 or matched[0]['sub']!=tx['partnerSpecificUserToken']:raise ValueError()
  except Exception:raise AuthenticationFailure('invalid_identity_response') from None
  # Check requested fixed claim values before releasing an identity assertion.
  claims=matched[0]
  for where in ['userinfo','id_token']:
   for name,detail in (tx['requestedClaims'].get(where) or {}).items():
    if where=='id_token' and name=='acr':continue
    if detail.get('essential') and name not in claims:raise AuthenticationFailure('essential_claim_unavailable')
    if detail.get('value') is not None and claims.get(name)!=detail['value']:raise AuthenticationFailure('claim_value_mismatch')
    if detail.get('values') and claims.get(name) not in detail['values']:raise AuthenticationFailure('claim_value_mismatch')
  return signed
 def token(self,form):
  if form.get('grant_type')!='authorization_code':raise AuthenticationFailure('unsupported_grant_type')
  client=self.clients.get(form.get('client_id'));self.client_assertion(form,client)
  code=bounded(form.get('code'),512);key=sha(code);tx=self.transaction('authcodegenerated',key)
  if tx['clientId']!=client['id'] or form.get('redirect_uri')!=tx['redirectUri'] or form.get('redirect_uri') not in client['redirectUris']:raise AuthenticationFailure('invalid_grant')
  proof=tx.get('proofKeyCodeExchange')
  if proof:
   verifier=form.get('code_verifier','')
   if not re.fullmatch('[A-Za-z0-9._~-]{43,128}',verifier) or not hmac.compare_digest(b64(hashlib.sha256(verifier.encode()).digest()),proof['codeChallenge']):raise AuthenticationFailure('invalid_grant')
  lock='kdbt-native-code-redemption::'+key;marker=secrets.token_urlsafe(24)
  if not self.redis.set(lock,marker,nx=True,ex=60):raise AuthenticationFailure('invalid_grant')
  try:
   tx=self.transaction('authcodegenerated',key);signed=self.exchange(tx);now=int(self.clock());ttl=self.settings['token_ttl']
   payload={'sub':tx['partnerSpecificUserToken'],'aud':client['id'],'iss':self.settings['issuer'],'exp':now+ttl,'iat':now,'client_id':client['id']}
   if tx['permittedScopes']:payload['scope']=' '.join(tx['permittedScopes'])
   access=self.signing.sign(payload);at_hash=b64(hashlib.sha256(access.encode()).digest()[:16]);tx.update(aHash=at_hash,encryptedKyc=self.cipher.encrypt(signed))
   response={'token_type':'Bearer','access_token':access,'expires_in':ttl}
   credential_scopes=set(tx.get('requestedCredentialScopes') or [])&set(tx['permittedScopes'])
   if credential_scopes:
    nonce=secrets.token_urlsafe(24);nonce_ttl=self.settings['cache_ttls']['vcissuance']
    self.cache.put('vcissuance',at_hash,{'cNonce':nonce,'cNonceIssuedEpoch':now,'cNonceExpireSeconds':nonce_ttl},template='vci')
    response.update(c_nonce=nonce,c_nonce_expires_in=nonce_ttl)
   else:
    provided={v for group in tx['providedAuthFactors'] or [] for v in group};acr=next((a for a in tx['requestedClaims']['id_token']['acr']['values'] if a in self.settings['acr_factors'] and {f['type'] for f in self.settings['acr_factors'][a]}<=provided),None)
    claims={'at_hash':at_hash,'sub':payload['sub'],'aud':client['id'],'acr':acr,'auth_time':tx['authTimeInSeconds'],'iss':payload['iss'],'exp':payload['exp'],'iat':now}
    if tx.get('nonce') is not None:claims['nonce']=tx['nonce']
    response['id_token']=self.signing.sign(claims)
   self.cache.move('authcodegenerated','userinfo',key,tx,new_identifier=at_hash)
   if tx.get('linkedTransactionId'):self.cache.delete('consented',tx['linkedTransactionId'])
   if tx.get('linkedCodeHash'):self.cache.delete('linkedcode',tx['linkedCodeHash'])
   return response
  finally:
   self.redis.eval("if redis.call('GET',KEYS[1])==ARGV[1] then redis.call('DEL',KEYS[1]) end",1,lock,marker)
 def access_transaction(self,token):
  value=self.signing.verify(token,issuer=self.settings['issuer']);client=self.clients.get(value.get('client_id'))
  if value.get('aud')!=client['id']:raise AuthenticationFailure('invalid_token')
  at_hash=b64(hashlib.sha256(token.encode()).digest()[:16]);tx=self.transaction('userinfo',at_hash)
  if tx['clientId']!=client['id'] or tx['partnerSpecificUserToken']!=value['sub'] or tx['aHash']!=at_hash:raise AuthenticationFailure('invalid_token')
  return tx
 def userinfo(self,token):
  tx=self.access_transaction(token);value=tx['encryptedKyc']
  if value.startswith(self.cipher.PREFIX):value=self.cipher.decrypt(value)
  # Original sessions store the provider-signed KYC assertion directly. Accept
  # that retained representation only after validating its pinned issuer key
  # and binding the subject to this authenticated client session.
  try:
   if jwt.get_unverified_header(value).get('alg')!='RS256':raise ValueError()
   verified=[]
   for key in self.settings['identity_verification_keys']:
    try:verified.append(jwt.decode(value,key,algorithms=['RS256'],options={'verify_aud':False,'require':['sub']}))
    except jwt.PyJWTError:pass
   if len(verified)!=1 or verified[0]['sub']!=tx['partnerSpecificUserToken']:raise ValueError()
  except Exception:raise AuthenticationFailure('invalid_identity_response') from None
  return value
