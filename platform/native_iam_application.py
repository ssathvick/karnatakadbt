"""Assembled native authentication, IAM business API and staff console backend.

All identity and permission decisions execute locally. Keycloak is retained as
the upstream identity provider; no legacy IAM HTTP endpoint is called.
"""
import hmac,json
from pathlib import Path
import httpx
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse,RedirectResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from native_oauth_api import create_native_oauth_api
from native_oidc import OAuthRejected
from native_iam_api import create_native_iam_api
from native_iam_access import NativeIamAccess
from native_iam_policy import NativeIamPolicy
from native_iam_business import IamBusinessError
from native_contract_models import ContractModels
from registry_metadata_api import RegistryAuthError,RegistryPrincipal
from registry_console_ui import mount_registry_console


def create_native_iam_application(engine,oidc,*,cookies,identity_factory,registration_allowed,catalogue_transport=None):
    if not callable(registration_allowed):raise ValueError('Explicit self-registration admission policy required')
    access=NativeIamAccess(engine)
    policy_store=NativeIamPolicy(engine)
    app=create_native_oauth_api(oidc,cookies=cookies,login_options=access.login_options)
    from console_bookmarks import mount_console_bookmarks
    mount_console_bookmarks(app,'iam')
    authenticate=app.state.authenticate_principal
    origins={'https://localhost:8445','https://localhost:8451'}
    def boundary(request):
        if request.headers.get('origin') and request.headers['origin'] not in origins:raise RegistryAuthError(403,'Origin is not allowed')
        if request.method not in {'GET','HEAD','OPTIONS'}:
            expected=request.cookies.get(cookies.name('X-CSRF-Token'),'');supplied=request.headers.get('x-csrf-token','')
            if not expected or not supplied or not hmac.compare_digest(expected.encode(),supplied.encode()):raise RegistryAuthError(403,'CSRF token missing or invalid')
    async def authority(request):
        boundary(request)
        try:claims,provider,token,tokens=await authenticate(request)
        except OAuthRejected:raise RegistryAuthError(401,'Verified staff session required') from None
        roles={client:value.get('roles',[]) for client,value in (claims.get('resource_access') or {}).items() if isinstance(value,dict)}
        permissions={p for item in access.permissions_for(roles,'iam-staff-ui') for p in item['permissions']}
        request.state.administration_bearer=token
        if tokens:
            response=JSONResponse({});cookies.set(response,tokens)
            request.state.registry_auth_cookies=response.headers.get_list('set-cookie')
        return RegistryPrincipal(claims['sub'],frozenset(permissions),claims.get('name'))
    @app.exception_handler(RegistryAuthError)
    async def denied(request,error):return JSONResponse({'error':error.message},status_code=error.status)
    from iam_console_catalogue import mount_iam_catalogue
    mount_iam_catalogue(app,authority,transport=catalogue_transport)
    @app.exception_handler(IamBusinessError)
    async def invalid(request,error):return JSONResponse({'error':error.message},status_code=400)
    @app.exception_handler(SQLAlchemyError)
    async def persistence(request,error):return JSONResponse({'error':'IAM persistence unavailable'},status_code=503)
    async def claims_for(request):
        claims,provider,token,tokens=await authenticate(request)
        roles={client:value.get('roles',[]) for client,value in (claims.get('resource_access') or {}).items() if isinstance(value,dict)}
        return claims,roles,tokens
    def result(value,tokens):
        response=JSONResponse(value)
        if tokens:cookies.set(response,tokens)
        return response
    async def payload(request,limit=8*1024*1024):
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>limit:raise RegistryAuthError(413,'Request is too large')
        try:return json.loads(body)
        except (ValueError,UnicodeDecodeError):raise RegistryAuthError(422,'Invalid JSON request') from None
    @app.get('/user-access/get_staff_portal_applications')
    async def applications(request:Request):
        claims,roles,tokens=await claims_for(request);return result(access.applications_for(roles),tokens)
    @app.get('/user-access/get_application_permissions_for_user')
    async def permissions(request:Request,application_mnemonic:str|None=None):
        claims,roles,tokens=await claims_for(request);return result(access.permissions_for(roles,application_mnemonic),tokens)
    @app.post('/user-access/get_permissions_for_roles')
    async def role_permissions(request:Request):
        # Original internal protocol is a non-authenticated read. No mutation
        # or caller identity is inferred from a role-name request.
        data=await payload(request,1024*1024);names=data.get('role_mnemonics') if isinstance(data,dict) else None
        if not isinstance(names,list) or len(names)>1000 or any(not isinstance(n,str) for n in names):return JSONResponse({'error':'Invalid roles'},status_code=422)
        return {'permissions':access.permissions_for_roles(names)}
    @app.post('/data-policies/evaluate_expression')
    async def expressions(request:Request):
        await authenticate(request)
        data=await payload(request,1024*1024);names=data.get('policy_mnemonics') if isinstance(data,dict) else None
        if not isinstance(names,list) or len(names)>1000 or any(not isinstance(n,str) for n in names):raise RegistryAuthError(422,'Invalid policy mnemonics')
        return {'policies':policy_store.evaluate_policies(names)}
    contract=json.loads(Path(__file__).with_name('iam_console_contract.json').read_text())
    model=ContractModels(contract).type({'$ref':'#/components/schemas/RegisterStaffPortalApplicationRequest'},'NativeRegistration')
    @app.post('/user-access/staff_portal_applications')
    async def register(request:Request):
        claims,roles,tokens=await claims_for(request)
        if not registration_allowed(claims):raise RegistryAuthError(403,'Application registration is not assigned')
        if not request.headers.get('authorization','').startswith('Bearer '):boundary(request)
        body=await payload(request)
        try:data=model.model_validate(body).model_dump(mode='json')
        except ValidationError:return JSONResponse({'error':'Invalid registration'},status_code=422)
        return result(access.register(data),tokens)
    # Loopback ASGI transport is used for login/logout only, never legacy IAM.
    transport=httpx.ASGITransport(app=app)
    business=create_native_iam_api(engine,'https://native-iam.internal',identity_factory=identity_factory,identity_transport=transport,authority=authority)
    # Copy only explicitly supported business and console routes. OAuth and
    # the access catalogue already have their own native handlers above.
    allowed=set(json.loads(Path(__file__).with_name('iam_console_permissions.json').read_text()))
    existing={(r.path,tuple(sorted(r.methods or []))) for r in app.routes}
    for route in business.routes:
        key=(route.path,tuple(sorted(route.methods or [])))
        if (route.path in allowed or route.path.startswith('/console/')) and key not in existing:
            app.router.routes.append(route);existing.add(key)
    staff=FastAPI(title='KarnatakaDBT native staff launcher')
    staff.exception_handlers.update(app.exception_handlers)
    mount_registry_console(staff,'https://native-iam.internal',list(origins),'https://localhost:8451/console/',profile='staff',authorize=authority,identity_transport=transport)
    for route in app.routes:
        if route.path in {'/user-access/get_staff_portal_applications','/user-access/get_application_permissions_for_user'}:staff.router.routes.append(route)
    # Relay browser-binding Set-Cookie through console login. Original login
    # helpers discarded it, breaking a callback on another subdomain.
    def console_login(request:Request):
        host=request.headers.get('host','')
        origin='https://localhost:8451' if host=='localhost:8451' else 'https://localhost:8445'
        binding=__import__('secrets').token_urlsafe(32)
        value=oidc.start('1',origin+'/console/',browser_binding=binding)
        response=RedirectResponse(value['redirectUrl'],status_code=303)
        response.set_cookie(cookies.name('X-OAuth-Binding'),binding,domain=cookies.domain,secure=True,httponly=True,samesite='lax',path='/auth',max_age=300)
        return response
    for target in [app,staff]:
        target.router.routes=[r for r in target.routes if r.path!='/console/login']
        target.add_api_route('/console/login',console_login,methods=['GET'],include_in_schema=False)
    app.state.staff_application=staff
    app.state.legacy_iam_http_dependency=False
    app.state.native_access_store=access
    return app
