"""Native agent OAuth transport; SQL catalogue remains read-only."""
import json,os,ssl
from pathlib import Path
import httpx,jwt,redis
from fastapi.responses import RedirectResponse
from sqlalchemy import create_engine,select,text
from native_iam_business import NativeIamBusiness
from native_oidc import NativeOIDC
from native_oauth_sessions import NativeOAuthSessions
from native_oauth_api import create_native_oauth_api,NativeAuthCookies
from native_oidc_providers import DatabaseOidcProviders

def build(settings):
    context=ssl.create_default_context(cafile=settings['trusted_ca_path']);engine=create_engine(settings['database_url'],hide_parameters=True,pool_pre_ping=True);store=NativeIamBusiness(engine)
    with engine.connect() as c:rows=[dict(row) for row in c.execute(select(store.tables['provider']).where(store.tables['provider'].c.active.is_(True))).mappings() if row['issuer']=='https://localhost:8444/realms/agent']
    if len(rows)!=1:raise ValueError('Exactly one active agent provider required')
    providers={}
    with httpx.Client(verify=context,trust_env=False,timeout=20) as http:
        for row in rows:
            result=http.get(row.get('server_metadata_url') or row['issuer']+'/.well-known/openid-configuration');result.raise_for_status();metadata=result.json()
            if metadata['issuer']!=row['issuer']:raise ValueError('Agent discovery issuer mismatch')
            keys=jwt.PyJWKClient(metadata['jwks_uri'],ssl_context=context)
            providers[str(row['id'])]={'issuer':row['issuer'],'authorization_endpoint':metadata['authorization_endpoint'],'token_endpoint':metadata['token_endpoint'],'callback_uri':row['oauth_callback_url'],'client_id':row['client_id'],'client_secret':row.get('client_secret'),'auth_method':row['token_endpoint_auth_method'],'access_audience':'account','algorithms':['RS256'],'key_lookup':lambda kid,keys=keys:keys.get_signing_key(kid).key,'scope':row.get('scope') or 'openid profile email','default_redirect_uri':'https://localhost:8443'}
            for field in ['userinfo_endpoint','end_session_endpoint']:
                if metadata.get(field):providers[str(row['id'])][field]=metadata[field]
    loader=DatabaseOidcProviders(engine,store.tables['provider'],verify=context,default_redirect_uri='https://localhost:8443')
    def agent_providers():
        values={identifier:provider for identifier,provider in loader().items() if provider['issuer']=='https://localhost:8444/realms/agent'}
        if len(values)!=1:raise ValueError('Exactly one available active agent provider required')
        return values
    config=settings['auth'];cache=redis.from_url(config['auth_redis_url'],decode_responses=True,socket_timeout=5,socket_connect_timeout=5)
    sessions=NativeOAuthSessions(cache,refresh_ttl=config['auth_refresh_token_ttl_seconds']);oidc=NativeOIDC(sessions,agent_providers(),redirect_origins=['https://localhost:8443'],verify=context,provider_loader=agent_providers)
    cookies=NativeAuthCookies(domain=config['auth_cookie_domain'],path=config['auth_cookie_path'],prefix=config.get('auth_cookie_prefix') or '')
    def login_options():
        available=agent_providers();catalogue=store.login_options()
        return {'loginProviders':[{**value,'protocol':'oidc'} for value in catalogue['loginProviders'] if str(value['id']) in available]}
    app=create_native_oauth_api(oidc,cookies=cookies,login_options=login_options)
    @app.middleware('http')
    async def native_backend(request,call_next):
        response=await call_next(request);response.headers['X-KarnatakaDBT-Native-Profile']='agent-iam';return response
    @app.get('/ping')
    def ping():return 'pong'
    @app.get('/auth/get_login_provider_redirect/{id}')
    def provider_redirect(id:int,redirect_uri:str='/'):
        import secrets
        binding=secrets.token_urlsafe(32);value=oidc.start(str(id),redirect_uri,browser_binding=binding)
        response=RedirectResponse(value['redirectUrl'])
        response.set_cookie(cookies.name('X-OAuth-Binding'),binding,domain=cookies.domain,secure=True,httponly=True,samesite='lax',path='/auth',max_age=300)
        return response
    @app.get('/health')
    def health():
        with engine.connect() as c:readonly=c.execute(text('SHOW transaction_read_only')).scalar_one()=='on'
        return {'ready':bool(cache.ping()) and (readonly or os.environ.get('KDBT_DEPLOYMENT_MODE')=='local'),'database_read_only':readonly,'agent_provider_count':len(agent_providers()),'business_writes_enabled':False,'provider_catalogue_dynamic':True}
    return app

if os.environ.get('KDBT_AGENT_OAUTH_SETTINGS'):app=build(json.loads(Path(os.environ['KDBT_AGENT_OAUTH_SETTINGS']).read_text()))
