"""Standalone native authorization API. No legacy business API forwarding."""
import asyncio,base64,copy,hmac,json,os,secrets,sqlite3,time
from pathlib import Path
import redis
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse,Response
from starlette.concurrency import run_in_threadpool
from native_auth_cache import AuthenticationFailure,JavaSessionCodec
from native_auth_clients import AdministrativeIdentity
from native_auth_engine import NativeAuthorization
from native_auth_linked import LinkedAuthorization

OPERATIONS={
 'updateClient':('PUT','/client-mgmt/oidc-client/{client_id}'),
 'updateOAuthClient':('PUT','/client-mgmt/oauth-client/{client_id}'),
 'getCredential':('POST','/vci/credential'),
 'uploadSignedCertificate':('POST','/system-info/uploadCertificate'),
 'getTokenV2':('POST','/oauth/v2/token'),'getToken':('POST','/oauth/token'),
 'linkTransactionV2':('POST','/linked-authorization/v2/link-transaction'),
 'saveConsentV2':('POST','/linked-authorization/v2/consent'),
 'authenticateV2':('POST','/linked-authorization/v2/authenticate'),
 'sendOtp':('POST','/linked-authorization/send-otp'),
 'linkTransaction':('POST','/linked-authorization/link-transaction'),
 'getLinkStatus':('POST','/linked-authorization/link-status'),
 'generateLinkCode':('POST','/linked-authorization/link-code'),
 'getAuthCode':('POST','/linked-authorization/link-auth-code'),
 'saveConsent':('POST','/linked-authorization/consent'),
 'authenticate':('POST','/linked-authorization/authenticate'),
 'createClient':('POST','/client-mgmt/oidc-client'),'createOAuthClient':('POST','/client-mgmt/oauth-client'),
 'bindWallet':('POST','/binding/wallet-binding'),'sendBindingOtp':('POST','/binding/binding-otp'),
 'authenticateEndUserV3':('POST','/authorization/v3/authenticate'),
 'getOauthDetailsV2':('POST','/authorization/v2/oauth-details'),
 'authenticateEndUserV2':('POST','/authorization/v2/authenticate'),
 'sendOtp_1':('POST','/authorization/send-otp'),'getOauthDetails':('POST','/authorization/oauth-details'),
 'authenticateEndUser':('POST','/authorization/authenticate'),
 'getAuthorizationCode':('POST','/authorization/auth-code'),
 'getMetadata':('GET','/vci/.well-known/openid-credential-issuer'),
 'getCertificate':('GET','/system-info/certificate'),'getUserInfo':('GET','/oidc/userinfo'),
 'getDiscoveryEndpoints':('GET','/oidc/.well-known/openid-configuration'),
 'getOAuthServerDiscoveryInfo':('GET','/oauth/.well-known/oauth-authorization-server'),
 'getAllJwks':('GET','/oauth/.well-known/jwks.json'),'getCsrfToken':('GET','/csrf/token')}
PREFIX='/v1/esignet'

def build(settings,*,redis_client=None,transport=None):
 from native_remaining_three_rehearsal import admission
 rehearsal=admission(settings,Path(__file__).parent,'authorization')
 if settings.get('environment') not in ['CANDIDATE','NATIVE']:raise ValueError('Explicit authority environment required')
 if settings['environment']=='NATIVE' and settings.get('candidate_device_origins'):raise ValueError('Candidate device fixtures cannot be enabled in production')
 if settings['environment']=='NATIVE' and not (settings.get('binding') and settings.get('credentials') and (settings.get('production_acceptance_verified') or rehearsal)):raise ValueError('Production requires wallet, credential issuance and complete acceptance')
 cache=redis_client or redis.Redis(**settings['redis']);codec=JavaSessionCodec(json.loads(Path(settings['session_templates']).read_text()))
 engine=NativeAuthorization(settings,cache,codec,transport=transport);linked=LinkedAuthorization(engine);admin=AdministrativeIdentity(settings['administration'])
 # Optional components are required for production activation; candidate
 # preparation can exercise the authorization engine independently.
 if settings.get('binding'):
  from native_auth_binding import WalletBinding
  engine.binding=WalletBinding(engine,settings['binding'])
 if settings.get('credentials'):
  from native_auth_credentials import CredentialIssuance
  engine.credentials=CredentialIssuance(engine,settings['credentials'])
 control=Path(settings['control_database']);control.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 with sqlite3.connect(control) as c:c.execute('CREATE TABLE IF NOT EXISTS authority(id INTEGER PRIMARY KEY CHECK(id=1),owner TEXT NOT NULL)');c.execute('INSERT OR IGNORE INTO authority VALUES(1,?)',(settings['environment'],))
 app=FastAPI(title='KarnatakaDBT native identity authorization',docs_url=None,redoc_url=None,openapi_url=None);app.state.engine=engine
 def owner():
  with sqlite3.connect(control) as c:return c.execute('SELECT owner FROM authority WHERE id=1').fetchone()[0]
 def envelope(value=None,error=None):return {'responseTime':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'),'response':value,'errors':[] if error is None else [{'errorCode':error,'errorMessage':error}]}
 @app.middleware('http')
 async def boundary(request,call_next):
  if request.url.path not in ['/health',PREFIX+'/actuator/health']:
   if rehearsal and not rehearsal.allows(request):return JSONResponse(envelope(error='rehearsal_fenced'),status_code=503)
   if owner()!=settings['environment']:return JSONResponse(envelope(error='writer_fenced'),status_code=503)
  if request.method not in ['GET','HEAD','OPTIONS']:
   data=bytearray()
   async for part in request.stream():
    data.extend(part)
    if len(data)>1024*1024:return JSONResponse(envelope(error='request_too_large'),status_code=413)
   request._body=bytes(data)
  response=await call_next(request);response.headers['Cache-Control']='no-store';response.headers['X-KarnatakaDBT-Authorization-Backend']='native'
  response.headers['X-Content-Type-Options']='nosniff';return response
 def handler(operation):
  async def invoke(request:Request):
   try:
    principal=None;token=request.headers.get('authorization','').removeprefix('Bearer ')
    scopes={
     'createClient':['add_oidc_client','esignet_admin_access'],'createOAuthClient':['add_oidc_client','esignet_admin_access'],
     'updateClient':['update_oidc_client','esignet_admin_access'],'updateOAuthClient':['update_oidc_client','esignet_admin_access'],
     'uploadSignedCertificate':['upload_certificate','esignet_admin_access'],'getCertificate':['get_certificate','esignet_admin_access'],
     'bindWallet':['wallet_binding'],'sendBindingOtp':['send_binding_otp']}
    if operation in scopes:principal=await run_in_threadpool(admin.authorize,token,scopes[operation])
    if request.method=='POST' and (operation in ['getOauthDetails','getOauthDetailsV2','sendOtp_1','authenticateEndUser','authenticateEndUserV2','authenticateEndUserV3','getAuthorizationCode','generateLinkCode','getLinkStatus','getAuthCode','sendOtp']):
     cookie=request.cookies.get('XSRF-TOKEN','');proof=request.headers.get('X-XSRF-TOKEN','')
     if not cookie or not proof or not hmac.compare_digest(cookie,proof):return JSONResponse(envelope(error='invalid_csrf_token'),status_code=403)
    if request.method=='GET':value=dict(request.query_params)
    elif operation in ['getToken','getTokenV2']:
     form=await request.form();value=dict(form)
     if any(len(form.getlist(k))!=1 for k in form):raise AuthenticationFailure('invalid_request')
    else:
     data=await request.json();value=data if operation=='getCredential' else data.get('request') if isinstance(data,dict) else None
     if not isinstance(value,dict):raise AuthenticationFailure('invalid_request')
    if operation=='getCsrfToken':
     proof=secrets.token_urlsafe(32);response=JSONResponse({'token':proof,'headerName':'X-XSRF-TOKEN','parameterName':'_csrf'});response.set_cookie('XSRF-TOKEN',proof,secure=settings['environment']=='NATIVE',httponly=False,samesite='lax');return response
    if operation in ['getDiscoveryEndpoints','getOAuthServerDiscoveryInfo']:return JSONResponse(settings['discovery'] if operation=='getDiscoveryEndpoints' else settings['oauth_discovery'])
    if operation=='getAllJwks':return JSONResponse(await run_in_threadpool(engine.signing.jwks))
    if operation=='getUserInfo':return Response(await run_in_threadpool(engine.userinfo,token),media_type='application/jwt')
    def dispatch():
     if operation in ['getOauthDetails','getOauthDetailsV2']:return engine.details(value,2 if operation.endswith('V2') else 1)
     if operation=='sendOtp_1':return engine.send_otp(value,request.headers)
     if operation in ['authenticateEndUser','authenticateEndUserV2','authenticateEndUserV3']:return engine.authenticate(value,request.headers,version=1 if operation=='authenticateEndUser' else 2)
     if operation=='getAuthorizationCode':return engine.code(value,request.headers)
     if operation in ['getToken','getTokenV2']:return engine.token(value)
     if operation in ['createClient','createOAuthClient']:return engine.clients.create(value,principal)
     if operation in ['updateClient','updateOAuthClient']:return engine.clients.update(request.path_params['client_id'],value,principal)
     if operation=='getCertificate':return engine.signing.certificate(value.get('applicationId'),value.get('referenceId') or '')
     if operation=='uploadSignedCertificate':return engine.signing.upload(value)
     if operation=='generateLinkCode':return linked.generate(value,request.headers)
     if operation in ['linkTransaction','linkTransactionV2']:return linked.link(value,2 if operation.endswith('V2') else 1)
     if operation=='getLinkStatus':return linked.status(value)
     if operation=='getAuthCode':return linked.code(value)
     if operation=='sendOtp':return engine.send_otp(value,linked=True)
     if operation in ['authenticate','authenticateV2']:return engine.authenticate(value,linked=True,version=2 if operation.endswith('V2') else 1)
     if operation in ['saveConsent','saveConsentV2']:return linked.consent(value,2 if operation.endswith('V2') else 1)
     if operation in ['bindWallet','sendBindingOtp']:
      if engine.binding is None:raise AuthenticationFailure('wallet_not_configured')
      return engine.binding.bind(value) if operation=='bindWallet' else engine.binding.send_otp(value)
     if operation in ['getCredential','getMetadata']:
      if engine.credentials is None:raise AuthenticationFailure('credential_issuer_not_configured')
      return engine.credentials.issue(value,token) if operation=='getCredential' else engine.credentials.metadata()
     raise AuthenticationFailure('invalid_request')
    result=await run_in_threadpool(dispatch)
    if operation in ['getAuthCode','getLinkStatus'] and result is None:
     deadline=time.monotonic()+settings.get('poll_timeout',25)
     while result is None and time.monotonic()<deadline:
      await asyncio.sleep(.2);result=await run_in_threadpool(dispatch)
     if result is None:raise AuthenticationFailure('link_code_expired' if operation=='getLinkStatus' else 'link_auth_code_timeout')
    return JSONResponse(result if operation in ['getToken','getTokenV2','getMetadata','getCredential'] else envelope(result))
   except AuthenticationFailure as error:
    if operation in ['getToken','getTokenV2']:return JSONResponse({'error':error.code,'error_description':error.code},status_code=401 if error.code=='invalid_client' else 400)
    if operation=='getCredential':return JSONResponse(getattr(error,'payload',{'error':error.code}),status_code=400)
    return JSONResponse(envelope(error=error.code),status_code=401 if operation=='getUserInfo' else 200)
   except (ValueError,TypeError,KeyError):return JSONResponse(envelope(error='invalid_request'),status_code=400)
  return invoke
 for operation,(method,path) in OPERATIONS.items():app.add_api_route(PREFIX+path,handler(operation),methods=[method],name=operation)
 @app.get('/health')
 @app.get(PREFIX+'/actuator/health')
 def health():return {'status':'UP','owner':owner(),'native_authorization':True,'candidate_operation_routes':len(OPERATIONS),
  'wallet_component_configured':engine.binding is not None,'credential_component_configured':engine.credentials is not None,'production_acceptance_verified':settings.get('production_acceptance_verified',False)}
 @app.get(PREFIX+'/v3/api-docs')
 def contract():
  value=json.loads(Path(settings['contract']).read_text());value['info']['title']='KarnatakaDBT native authorization compatibility API';return value
 return app

if os.environ.get('KDBT_NATIVE_AUTH_SETTINGS'):app=build(json.loads(Path(os.environ['KDBT_NATIVE_AUTH_SETTINGS']).read_text()))
