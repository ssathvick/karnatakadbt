"""Own console gateway; retained business APIs remain explicit dependencies.

Every browser request is admitted by authoritative IAM, local JWT verification
for role-gated services, the original role scope, and an exact route contract.
There is no anonymous/development mode or arbitrary upstream URL endpoint.
"""
import dataclasses,json,ssl
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import quote,urlsplit
import httpx,jwt
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import JSONResponse,Response
from registry_console_auth import RegistryConsoleAuthorizer
from registry_metadata_api import RegistryAuthError
from approval_auth import ApprovalTokenVerifier
from registry_console_ui import mount_registry_console

PROFILES={
    'iam':{'host':'localhost:8445','client':'iam-staff-ui'},
    'consent':{'host':'localhost:8449','client':''},
    'partner':{'host':'localhost:8448','client':''},
    'staff':{'host':'localhost:8451','client':''},
}

class AdministrationAuthority:
    def __init__(self,profile,iam_url,allowed_origins,transport=None,key_lookup=None):
        if profile not in PROFILES:raise ValueError('Unknown administration profile')
        self.profile=profile
        self.iam=RegistryConsoleAuthorizer(iam_url,client_id=PROFILES[profile]['client'],allowed_origins=allowed_origins,transport=transport)
        issuer='https://localhost:8444/realms/staff'
        if profile in {'consent','partner'}:
            if key_lookup is None:
                key_lookup=jwt.PyJWKClient(issuer+'/protocol/openid-connect/certs',ssl_context=ssl.create_default_context(cafile='/runtime/caddy/pki/authorities/local/root.crt')).get_signing_key_from_jwt
            self.verify=ApprovalTokenVerifier([issuer],'account',issuer+'/protocol/openid-connect/certs',key_lookup=key_lookup)
    async def __call__(self,request):
        principal=await self.iam(request)
        authorization=request.headers.get('authorization','')
        token=authorization[7:].strip() if authorization.lower().startswith('bearer ') else request.cookies.get('X-Access-Token')
        if not authorization:
            for value in getattr(request.state,'registry_auth_cookies',[]):
                parsed=SimpleCookie();parsed.load(value)
                if 'X-Access-Token' in parsed:token=parsed['X-Access-Token'].value
        if not token:raise RegistryAuthError(401,'Verified staff access token required')
        if self.profile in {'consent','partner'}:
            try:identity=self.verify(token)
            except HTTPException as error:raise RegistryAuthError(error.status_code,'Staff token could not be verified') from None
            if identity.subject!=principal.subject:raise RegistryAuthError(401,'Staff identity mismatch')
            if self.profile=='consent':
                roles=identity.roles;permissions={'role:'+role for role in ['CONSENT_MANAGER_ADMIN','CONSENT_MANAGER_APPROVER'] if role in roles}
            else:
                # Signature/issuer/audience are already verified above. Restrict
                # the partner role to its original realm-or-client location.
                claims=jwt.decode(token,options={'verify_signature':False})
                roles=set((claims.get('realm_access') or {}).get('roles') or [])
                roles.update((((claims.get('resource_access') or {}).get('commons-services-staff-portal') or {}).get('roles') or []))
                permissions={'role:partner_manager'} if 'partner_manager' in roles else set()
            principal=dataclasses.replace(principal,permissions=frozenset(permissions))
        request.state.administration_bearer=token
        return principal

def create_administration_console(profile,iam_url,upstream_url,*,identity_transport=None,upstream_transport=None,key_lookup=None):
    if profile not in PROFILES:raise ValueError('Unknown administration profile')
    upstream=urlsplit(upstream_url)
    if upstream.scheme!='http' or not upstream.hostname or upstream.username or upstream.password or upstream.path not in {'','/'} or upstream.query or upstream.fragment:raise ValueError('Explicit internal service origin required')
    origin='https://'+PROFILES[profile]['host'];authority=AdministrationAuthority(profile,iam_url,[origin],transport=identity_transport,key_lookup=key_lookup)
    folder=Path(__file__).parent;contract=json.loads((folder/(profile+'_console_contract.json')).read_text());access=json.loads((folder/(profile+'_console_permissions.json')).read_text())
    app=FastAPI(title='KarnatakaDBT '+profile+' console candidate')
    mount_registry_console(app,iam_url,[origin],origin+'/console/',profile=profile,authorize=authority,identity_transport=identity_transport)
    def endpoint(template,method):
        required=frozenset(access[template]['required_permissions'])
        async def handle(request:Request):
            try:
                principal=await authority(request)
                if not required.issubset(principal.permissions):raise RegistryAuthError(403,'Assigned console access required')
                target=template
                for name,value in request.path_params.items():
                    if value in {'.','..'} or '/' in value or '\\' in value:raise RegistryAuthError(400,'Invalid resource identifier')
                    target=target.replace('{'+name+'}',quote(value,safe=''))
                body=b''
                async for chunk in request.stream():
                    body+=chunk
                    if len(body)>8*1024*1024:raise RegistryAuthError(413,'Console request is too large')
                headers={'authorization':'Bearer '+request.state.administration_bearer}
                for name in ['content-type','accept']:
                    if name in request.headers:headers[name]=request.headers[name]
                # IAM and partner legacy handlers may still validate browser
                # CSRF even when a bearer is present. Forward the matched CSRF
                # cookie/header only; never send ID or refresh cookies upstream.
                csrf=request.cookies.get('X-CSRF-Token')
                if csrf:headers['cookie']='X-CSRF-Token='+csrf;headers['x-csrf-token']=csrf
                async with httpx.AsyncClient(timeout=20,trust_env=False,follow_redirects=False,transport=upstream_transport) as client:
                    result=await client.request(method,upstream_url.rstrip('/')+target,params=list(request.query_params.multi_items()),content=body or None,headers=headers)
                response=Response(result.content,status_code=result.status_code,headers={'content-type':result.headers.get('content-type','application/json'),'cache-control':'no-store','x-content-type-options':'nosniff'})
                for cookie in getattr(request.state,'registry_auth_cookies',[]):response.headers.append('set-cookie',cookie)
                return response
            except RegistryAuthError as error:return JSONResponse({'error':error.message},status_code=error.status,headers={'cache-control':'no-store'})
            except httpx.HTTPError:return JSONResponse({'error':'Administration service unavailable'},status_code=503,headers={'cache-control':'no-store'})
        return handle
    for path in access:
        for method in contract['paths'][path]:
            if method in {'get','post','put','patch','delete'}:app.add_api_route(path,endpoint(path,method.upper()),methods=[method.upper()],include_in_schema=False)
    app.state.legacy_business_api_retained=True
    return app
