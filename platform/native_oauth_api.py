"""Native IAM login/session HTTP routes with compatible browser cookie names."""
import secrets
from urllib.parse import urlencode
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from native_oidc import OAuthRejected


class NativeAuthCookies:
    names=('X-Access-Token','X-ID-Token','X-Session-Id','X-CSRF-Token')
    def __init__(self,*,domain,path='/',prefix='',secure=True,access_max_age=1800,session_max_age=1800):
        if not domain or not path.startswith('/') or not secure:
            raise ValueError('Explicit secure cookie scope required')
        self.domain,self.path,self.prefix,self.secure=domain,path,prefix,secure
        self.access_age,self.session_age=access_max_age,session_max_age
    def name(self,name):return self.prefix+name
    def clear(self,response):
        for name in self.names:
            response.delete_cookie(self.name(name),path=self.path,domain=self.domain,secure=True,httponly=name!='X-CSRF-Token',samesite='lax')
    def set(self,response,tokens,session_id=None):
        values={'X-Access-Token':tokens['access_token'],'X-ID-Token':tokens.get('id_token'),
                'X-Session-Id':session_id,'X-CSRF-Token':secrets.token_urlsafe(32)}
        for name,value in values.items():
            if value is not None:
                response.set_cookie(self.name(name),value,path=self.path,domain=self.domain,secure=True,httponly=name!='X-CSRF-Token',
                                    samesite='lax',max_age=self.session_age if name in {'X-Session-Id','X-CSRF-Token'} else self.access_age)


def create_native_oauth_api(oidc,*,cookies,login_options):
    app=FastAPI(title='KarnatakaDBT native IAM authentication')
    @app.middleware('http')
    async def no_store(request,call_next):
        response=await call_next(request);response.headers['cache-control']='no-store';response.headers['x-content-type-options']='nosniff'
        return response
    @app.exception_handler(OAuthRejected)
    async def rejected(request,error):return JSONResponse({'error':'Authentication rejected'},status_code=401)
    def provider_for_token(token):
        import jwt
        try:issuer=jwt.decode(token,options={'verify_signature':False}).get('iss')
        except (jwt.PyJWTError,ValueError,TypeError):raise OAuthRejected() from None
        providers=[p for p in oidc.providers.values() if p['issuer']==issuer and p.get('active',True)]
        if len(providers)!=1:raise OAuthRejected()
        return providers[0]
    async def principal(request):
        header=request.headers.get('authorization','');bearer=header.startswith('Bearer ')
        token=header[7:] if bearer else request.cookies.get(cookies.name('X-Access-Token'))
        sid=request.cookies.get(cookies.name('X-Session-Id'));tokens=None
        if not token:raise OAuthRejected()
        provider=provider_for_token(token)
        if not bearer and (not sid or not oidc.sessions.read_session(sid)):
            raise OAuthRejected()
        try:
            claims=oidc._claims(token,provider,audience=provider['access_audience'],required=['iss','sub','aud','exp','iat'])
        except OAuthRejected:
            if bearer or not sid:raise
            tokens=await oidc.refresh(sid);token=tokens['access_token']
            claims=oidc._claims(token,provider,audience=provider['access_audience'],required=['iss','sub','aud','exp','iat'])
        if not bearer and claims.get('sid')!=sid:raise OAuthRejected()
        return claims,provider,token,tokens
    def response_for(value,tokens):
        response=JSONResponse(value)
        if tokens:cookies.set(response,tokens)
        return response
    @app.get('/auth/get_login_providers')
    def providers():return login_options()
    @app.post('/auth/start_authentication_transaction')
    def start(id:int,redirect_uri:str='/'):
        binding=secrets.token_urlsafe(32)
        response=JSONResponse(oidc.start(str(id),redirect_uri,browser_binding=binding))
        response.set_cookie(cookies.name('X-OAuth-Binding'),binding,domain=cookies.domain,secure=True,httponly=True,samesite='lax',path='/auth',max_age=300)
        return response
    @app.get('/auth/callback')
    async def callback(request:Request):
        value=await oidc.complete(request.query_params.get('state'),request.query_params.get('code'),browser_binding=request.cookies.get(cookies.name('X-OAuth-Binding')))
        response=RedirectResponse(value['redirect_uri']);cookies.clear(response);cookies.set(response,value['token_response'],value['session_id'])
        response.delete_cookie(cookies.name('X-OAuth-Binding'),domain=cookies.domain,path='/auth',secure=True,httponly=True,samesite='lax')
        return response
    @app.get('/auth/get_user_profile')
    async def profile(request:Request):
        claims,provider,token,tokens=await principal(request)
        roles={key:sorted(value['roles']) for key,value in (claims.get('resource_access') or {}).items() if isinstance(value,dict) and value.get('roles')}
        return response_for({'scheme':'bearer','name':claims.get('name'),'sub':claims['sub'],'aud':claims['aud'],'client_roles':roles or None},tokens)
    @app.get('/auth/get_logged_in_user')
    async def user(request:Request):
        claims,provider,token,tokens=await principal(request)
        # Profile enrichment uses only an explicitly configured fixed endpoint.
        endpoint=provider.get('userinfo_endpoint')
        if endpoint:
            from urllib.parse import urlsplit
            parsed=urlsplit(endpoint)
            if parsed.scheme!='https' or parsed.username or parsed.password:raise OAuthRejected()
            try:
                async with httpx.AsyncClient(timeout=15,trust_env=False,follow_redirects=False,transport=oidc.transport,verify=oidc.verify) as client:
                    result=await client.get(endpoint,headers={'authorization':'Bearer '+token})
                    if result.status_code!=200:raise OAuthRejected()
                    info=result.json()
                    if info.get('sub')!=claims['sub']:raise OAuthRejected()
                    claims={**claims,**info}
            except (httpx.HTTPError,ValueError):raise OAuthRejected() from None
        fields=['sub','email_verified','address','name','preferred_username','given_name','family_name','email']
        return response_for({field:claims.get(field,{} if field=='address' else None) for field in fields},tokens)
    @app.get('/auth/logout')
    async def logout(request:Request):
        claims,provider,token,tokens=await principal(request)
        sid=request.cookies.get(cookies.name('X-Session-Id'))
        # A bearer caller may revoke its own session, never an unrelated cookie.
        if sid and claims.get('sid')!=sid:raise OAuthRejected()
        oidc.sessions.delete_session(sid or claims.get('sid'))
        target=oidc._redirect(provider.get('default_redirect_uri','/'))
        endpoint=provider.get('end_session_endpoint')
        if endpoint:
            from urllib.parse import urlsplit
            parsed=urlsplit(endpoint)
            if parsed.scheme!='https' or parsed.username or parsed.password:raise OAuthRejected()
            params={'post_logout_redirect_uri':target,'client_id':provider['client_id']}
            # Validate ID token before disclosing it to the configured IdP.
            identity=request.cookies.get(cookies.name('X-ID-Token'))
            if identity:
                identity_claims=oidc._claims(identity,provider,audience=provider['client_id'],required=['iss','sub','aud','exp'])
                if identity_claims['sub']!=claims['sub']:raise OAuthRejected()
                params['id_token_hint']=identity
            target=endpoint+('&' if '?' in endpoint else '?')+urlencode(params)
        response=RedirectResponse(target);cookies.clear(response);return response
    @app.post('/auth/backchannel-logout')
    async def backchannel(request:Request):
        form=await request.form();token=form.get('logout_token')
        if not isinstance(token,str) or not token:raise OAuthRejected()
        oidc.backchannel_logout(token);return Response(status_code=200)
    app.state.native_auth_operations=7
    app.state.authenticate_principal=principal
    app.state.production_authentication_switched=False
    return app
