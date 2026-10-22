"""Staff-session administration UI over the native operation catalogue only."""
import hmac,json,re
from http.cookies import SimpleCookie,CookieError
from pathlib import Path
from urllib.parse import urlsplit,quote
import httpx,jwt
from fastapi import Request
from fastapi.responses import FileResponse,JSONResponse,RedirectResponse
from starlette.concurrency import run_in_threadpool

PREFIX='/v1/certify/admin'

def mount_console(app,settings,administrator,operations,*,identity_transport=None):
    origin=settings['public_url'].rstrip('/')
    parsed=urlsplit(origin)
    if origin!='https://localhost:8443/registration/credential-admin':raise ValueError('Approved staff console return URL required')
    iam=settings['iam_url'].rstrip('/')
    if iam!='http://127.0.0.1:18110':raise ValueError('Pinned native staff IAM required')
    folder=Path(__file__).with_name('credential-console')
    catalogue={}
    for group,values in operations.items():
        for name,value in values.items():
            method,path=value[:2]
            if name in catalogue:raise ValueError('Unique operation identifiers required')
            catalogue[name]={'id':name,'group':group,'method':method,'path':path,
                'parameters':re.findall(r'\{([^}]+)\}',path),'encoding':'form' if name in {'credentialToken','interactiveAuthorization'} else 'json'}
    def protect(response):
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
            'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; object-src 'none'; form-action 'self'; frame-ancestors 'self'"})
        return response
    def reply(value,status=200,cookies=()):
        response=protect(JSONResponse(value,status_code=status))
        for cookie in cookies:response.headers.append('set-cookie',cookie)
        return response
    async def principal(request,write=False):
        if request.headers.get('origin') not in {None,parsed.scheme+'://'+parsed.netloc}:raise PermissionError('origin')
        if write:
            cookie=request.cookies.get('X-CSRF-Token','');header=request.headers.get('x-csrf-token','')
            if not cookie or not header or not hmac.compare_digest(cookie.encode(),header.encode()):raise PermissionError('csrf')
        auth={name:request.cookies[name] for name in ['X-Access-Token','X-ID-Token','X-Session-Id'] if name in request.cookies}
        # Browser sessions must remain authoritative in native IAM. A raw bearer
        # or the candidate's static fixture token never establishes this session.
        if not auth.get('X-Access-Token') or not auth.get('X-Session-Id'):raise PermissionError('session')
        async with httpx.AsyncClient(trust_env=False,timeout=10,transport=identity_transport) as client:
            response=await client.get(iam+'/auth/get_user_profile',cookies=auth,follow_redirects=False)
        if response.status_code!=200:raise PermissionError('session')
        identity=response.json();token=auth['X-Access-Token'];cookies=response.headers.get_list('set-cookie')
        if not isinstance(identity,dict):raise PermissionError('profile')
        for value in cookies:
            parsed_cookie=SimpleCookie()
            try:parsed_cookie.load(value)
            except CookieError:raise PermissionError('refresh')
            if 'X-Access-Token' in parsed_cookie:token=parsed_cookie['X-Access-Token'].value
        if not await run_in_threadpool(administrator.authorize,token):raise PermissionError('administrator')
        claims=jwt.decode(token,options={'verify_signature':False})
        if identity.get('sub')!=claims.get('sub'):raise PermissionError('subject')
        return token,identity,cookies
    def static_handler(filename,media):
        path=folder/filename
        def static():return protect(FileResponse(path,media_type=media))
        return static
    for filename,media in [('index.html','text/html'),('console.js','text/javascript'),('console.css','text/css')]:
        app.add_api_route(PREFIX+('/' if filename=='index.html' else '/'+filename),static_handler(filename,media),methods=['GET'],include_in_schema=False)
    @app.get(PREFIX+'/login',include_in_schema=False)
    async def login():
        try:
            async with httpx.AsyncClient(trust_env=False,timeout=10,transport=identity_transport) as client:
                response=await client.post(iam+'/auth/start_authentication_transaction',params={'id':1,'redirect_uri':origin+'/'})
            response.raise_for_status();target=response.json()['redirectUrl'];url=urlsplit(target)
            if url.scheme!='https' or url.netloc!='localhost:8444' or not url.path.startswith('/realms/staff/protocol/openid-connect/auth'):raise ValueError('redirect')
            result=protect(RedirectResponse(target,status_code=303))
            for cookie in response.headers.get_list('set-cookie'):result.headers.append('set-cookie',cookie)
            return result
        except (httpx.HTTPError,ValueError,KeyError):return reply({'error':'Staff sign-in is unavailable'},503)
    @app.get(PREFIX+'/session',include_in_schema=False)
    async def session(request:Request):
        try:
            token,identity,cookies=await principal(request)
            return reply({'name':identity.get('name') or 'Administrator','operations':list(catalogue.values())},cookies=cookies)
        except PermissionError:return reply({'error':'Administrator sign-in required'},403)
        except (httpx.HTTPError,ValueError,KeyError,TypeError):return reply({'error':'Session verification unavailable'},503)
    @app.post(PREFIX+'/logout',include_in_schema=False)
    async def logout(request:Request):
        try:
            await principal(request,True)
            async with httpx.AsyncClient(trust_env=False,timeout=10,transport=identity_transport) as client:
                response=await client.get(iam+'/auth/logout',cookies={k:v for k,v in request.cookies.items() if k in {'X-Access-Token','X-ID-Token','X-Session-Id'}},follow_redirects=False)
            if response.status_code not in {200,204,302,303,307}:raise PermissionError('logout')
            return reply({'signed_out':True},cookies=response.headers.get_list('set-cookie'))
        except PermissionError:return reply({'error':'Sign-out rejected'},403)
        except (httpx.HTTPError,ValueError):return reply({'error':'Sign-out unavailable'},503)
    @app.post(PREFIX+'/execute',include_in_schema=False)
    async def execute(request:Request):
        try:
            token,identity,cookies=await principal(request,True)
            body=bytearray()
            async for part in request.stream():
                body.extend(part)
                if len(body)>12*1024*1024:return reply({'error':'Request too large'},413)
            value=json.loads(body)
            if not isinstance(value,dict) or set(value)-{'operation','parameters','query','body','credentialAccessToken'}:raise ValueError('request')
            operation=catalogue[value['operation']];path=operation['path'];parameters=value.get('parameters',{})
            if operation['id']!='signPDF' and len(body)>1024*1024:return reply({'error':'Request too large'},413)
            if not isinstance(parameters,dict) or set(parameters)!=set(operation['parameters']):raise ValueError('parameters')
            for name,identifier in parameters.items():
                if not isinstance(identifier,str) or identifier in {'.','..'} or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}',identifier):raise ValueError('identifier')
                path=path.replace('{'+name+'}',quote(identifier,safe=''))
            query=value.get('query',{})
            if not isinstance(query,dict) or len(query)>30 or any(not isinstance(k,str) or not isinstance(v,str) or len(k)>128 or len(v)>4096 for k,v in query.items()):raise ValueError('query')
            holder=value.get('credentialAccessToken')
            if holder is not None:
                if operation['id'] not in {'issueCredential','issueCredentialV11','issueCredentialV12'} or not isinstance(holder,str) or not 1<=len(holder)<=16384:raise ValueError('credential token')
                token=holder
            payload=value.get('body',{})
            if not isinstance(payload,dict):raise ValueError('body')
            if operation['encoding']=='form' and any(not isinstance(k,str) or not isinstance(v,str) for k,v in payload.items()):raise ValueError('form')
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://native-credential-inprocess',timeout=30) as client:
                arguments={'data':payload} if operation['encoding']=='form' else {'json':payload}
                forwarded={'Authorization':'Bearer '+token}
                # The outer middleware already verified this private, expiring
                # receipt capability. Preserve it across the internal dispatch.
                rehearsal=request.headers.getlist('x-kdbt-private-rehearsal')
                if len(rehearsal)==1:forwarded['x-kdbt-private-rehearsal']=rehearsal[0]
                response=await client.request(operation['method'],'/v1/certify'+path,params=query,headers=forwarded,**arguments)
            try:result=response.json()
            except ValueError:result=response.text
            return reply({'status':response.status_code,'contentType':response.headers.get('content-type'),'result':result},cookies=cookies)
        except PermissionError:return reply({'error':'Administrator session and CSRF proof required'},403)
        except (ValueError,KeyError,TypeError):return reply({'error':'Select a valid operation and request'},400)
        except httpx.HTTPError:return reply({'error':'Native operation unavailable'},503)
