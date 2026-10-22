"""Opt-in native registry frontend, sharing the verified IAM cookie protocol."""
import json
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from fastapi import Request
from fastapi.responses import FileResponse,JSONResponse,RedirectResponse
from registry_console_auth import RegistryConsoleAuthorizer
from registry_metadata_api import RegistryAuthError

def mount_registry_console(app,iam_url,allowed_origins,public_console_url,profile='registry',authorize=None,identity_transport=None):
    if profile in {'iam','master-data','partner','registry'}:
        from console_bookmarks import mount_console_bookmarks
        mount_console_bookmarks(app,profile)
    profiles={'registry':{'client':'register-staff-portal','host':'localhost:8446','contract':'registry_full_contract.json','permissions':'registry_auth_contract.json','folder':'registry-console'},
              'master-data':{'client':'master-data-ui','host':'localhost:8447','contract':'master_data_contract.json','permissions':'master_data_console_permissions.json','folder':'master-data-console'}}
    for name,host,client in [('iam','localhost:8445','iam-staff-ui'),('consent','localhost:8449',''),('partner','localhost:8448',''),('staff','localhost:8451','')]:
        profiles[name]={'client':client,'host':host,'contract':name+'_console_contract.json','permissions':name+'_console_permissions.json','folder':name+'-console'}
    if profile not in profiles:raise ValueError('Unknown console profile')
    spec=profiles[profile]
    public=urlsplit(public_console_url)
    if public.scheme!='https' or public.netloc!=spec['host'] or public.path!='/console/' or public.query or public.fragment:
        raise ValueError('Explicit approved registry console return URL required')
    folder=Path(__file__).with_name(spec['folder']);shared=Path(__file__).with_name('registry-console')
    authorizer=authorize or RegistryConsoleAuthorizer(iam_url,client_id=spec['client'],allowed_origins=allowed_origins)
    def protect(response):
        response.headers['cache-control']='no-store';response.headers['x-content-type-options']='nosniff';response.headers['referrer-policy']='no-referrer'
        response.headers['content-security-policy']="default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors https://localhost:8443 https://"+spec['host']
        if profile=='staff':response.headers['content-security-policy']+="; img-src 'self' data:"
        return response
    @app.get('/console/',include_in_schema=False)
    def home():return protect(FileResponse(folder/'index.html'))
    @app.get('/console/console.js',include_in_schema=False)
    def javascript():return protect(FileResponse(shared/'console.js',media_type='text/javascript'))
    @app.get('/console/identifier-fields.js',include_in_schema=False)
    def identifier_fields():return protect(FileResponse(shared/'identifier-fields.js',media_type='text/javascript'))
    if profile=='staff':
        @app.get('/console/launcher.js',include_in_schema=False)
        def launcher():return protect(FileResponse(folder/'launcher.js',media_type='text/javascript'))
        @app.get('/console/launcher.css',include_in_schema=False)
        def launcher_style():return protect(FileResponse(folder/'launcher.css',media_type='text/css'))
    if profile=='iam':
        @app.get('/console/iam-editor.js',include_in_schema=False)
        def iam_editor():return protect(FileResponse(folder/'editor.js',media_type='text/javascript'))
    if profile=='registry':
        @app.get('/console/designer.js',include_in_schema=False)
        def registry_designer():return protect(FileResponse(folder/'designer.js',media_type='text/javascript'))
        @app.get('/record-access-denied',include_in_schema=False)
        @app.get('/{locale}/record-access-denied',include_in_schema=False)
        def registry_denied(locale:str='en'):return protect(FileResponse(folder/'access-denied.html',status_code=403))
    @app.get('/console/console.css',include_in_schema=False)
    def stylesheet():return protect(FileResponse(shared/'console.css',media_type='text/css'))
    @app.get('/console/contract.json',include_in_schema=False)
    def contract():return protect(FileResponse(folder.parent/spec['contract'],media_type='application/json'))
    @app.get('/console/permissions.json',include_in_schema=False)
    def permissions():return protect(FileResponse(folder.parent/spec['permissions'],media_type='application/json'))
    @app.get('/console/session',include_in_schema=False)
    async def session(request:Request):
        try:principal=await authorizer(request)
        except RegistryAuthError as error:return protect(JSONResponse({'error':error.message},status_code=error.status))
        response=protect(JSONResponse({'name':principal.name,'permissions':sorted(principal.permissions)}))
        for cookie in getattr(request.state,'registry_auth_cookies',[]):response.headers.append('set-cookie',cookie)
        return response
    @app.get('/console/login',include_in_schema=False)
    async def login():
        try:
            async with httpx.AsyncClient(trust_env=False,timeout=10,transport=identity_transport) as client:
                response=await client.post(iam_url.rstrip('/')+'/auth/start_authentication_transaction',params={'id':1,'redirect_uri':public_console_url},follow_redirects=False)
                response.raise_for_status();target=response.json()['redirectUrl'];parsed=urlsplit(target)
                if parsed.scheme!='https' or parsed.hostname!='localhost' or parsed.username or parsed.password or not parsed.path.startswith('/realms/staff/protocol/openid-connect/auth'):raise ValueError('Unapproved identity redirect')
                result=protect(RedirectResponse(target,status_code=303))
                for value in response.headers.get_list('set-cookie'):result.headers.append('set-cookie',value)
                return result
        except (httpx.HTTPError,ValueError,KeyError,TypeError):return protect(JSONResponse({'error':'Staff sign-in is temporarily unavailable'},status_code=503))
    @app.post('/console/logout',include_in_schema=False)
    async def logout(request:Request):
        try:await authorizer(request)
        except RegistryAuthError as error:return protect(JSONResponse({'error':error.message},status_code=error.status))
        # Authorizer validates the double-submit CSRF token for this POST.
        cookies={key:request.cookies[key] for key in ['X-Access-Token','X-ID-Token','X-Session-Id'] if key in request.cookies}
        try:
            async with httpx.AsyncClient(trust_env=False,timeout=10,transport=identity_transport) as client:
                response=await client.get(iam_url.rstrip('/')+'/auth/logout',cookies=cookies,follow_redirects=False)
            if response.status_code not in {200,204,302,303,307}:raise ValueError('Logout failed')
            result=protect(JSONResponse({'signed_out':True}))
            for name in ['X-Access-Token','X-ID-Token','X-Session-Id','X-CSRF-Token']:result.delete_cookie(name,path='/')
            for cookie in response.headers.get_list('set-cookie'):result.headers.append('set-cookie',cookie)
            return result
        except (httpx.HTTPError,ValueError):return protect(JSONResponse({'error':'Sign-out could not be completed'},status_code=503))
