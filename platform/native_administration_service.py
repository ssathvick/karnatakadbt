"""Deployed native administration services with database-enforced standby.

No original business backend is used. Keycloak and the compatible Redis
session store remain upstream infrastructure. Writes stay disabled until a
separate coordinated cutover supplies writable credentials and admission.
"""
import json,os,ssl
from pathlib import Path
import httpx,jwt,redis
from sqlalchemy import create_engine,select,text
from fastapi.responses import JSONResponse
from native_iam_business import NativeIamBusiness
from native_iam_application import create_native_iam_application
from native_identity_admin import NativeIdentityAdmin
from native_identity_recovery import RecoverableIdentityAdmin
from native_oidc import NativeOIDC
from native_oauth_api import NativeAuthCookies
from native_oauth_sessions import NativeOAuthSessions
from native_consent_api import create_native_consent_api
from native_consent_runtime import build_native_consent_public
from native_partner_api import create_native_partner_api
from native_oidc_providers import DatabaseOidcProviders
from native_administration_admission import configure_writer,AdministrationWriterAdmission


def build(settings):
    profile=settings['profile'];engine=create_engine(settings['database_url'],hide_parameters=True,pool_pre_ping=True)
    writable=settings.get('business_writes_enabled')
    if type(writable) is not bool:raise ValueError('Explicit administration writer mode required')
    domain='consent' if profile in {'consent-staff','consent-public'} else profile
    ownership=configure_writer(engine,settings,domain)
    context=ssl.create_default_context(cafile=settings['trusted_ca_path'])
    if profile=='iam':
        store=NativeIamBusiness(engine)
        recovery_key=None
        if settings.get('identity_recovery_settings_path'):
            recovery_path=Path(settings['identity_recovery_settings_path'])
            if recovery_path.stat().st_mode&0o077:raise ValueError('Identity recovery settings must be private')
            recovery_key=json.loads(recovery_path.read_text())['identity_recovery_key']
        def identity_admin(token):
            admin=NativeIdentityAdmin(settings['keycloak_admin_origin'],token)
            return RecoverableIdentityAdmin(engine,admin,recovery_key) if recovery_key else admin
        config=settings['auth'];sessions=NativeOAuthSessions(redis.from_url(config['auth_redis_url'],decode_responses=True,socket_timeout=5,socket_connect_timeout=5),refresh_ttl=config['auth_refresh_token_ttl_seconds'])
        provider_loader=DatabaseOidcProviders(engine,store.tables['provider'],verify=context,default_redirect_uri='https://localhost:8445/console/')
        oidc=NativeOIDC(sessions,provider_loader(),redirect_origins=settings['redirect_origins'],verify=context,provider_loader=provider_loader)
        cookies=NativeAuthCookies(domain=config['auth_cookie_domain'],path=config['auth_cookie_path'],prefix=config['auth_cookie_prefix'])
        app=create_native_iam_application(engine,oidc,cookies=cookies,identity_factory=identity_admin,registration_allowed=lambda claims:claims.get('azp') in settings['registration_client_ids'])
    elif profile=='consent-staff':app=create_native_consent_api(engine,settings['native_iam_url'],approval_url=settings['approval_url'],approval_enabled=False)
    elif profile=='partner':app=create_native_partner_api(engine,settings['native_iam_url'],audit_config=settings.get('audit_config'),expose_internal_public_keys=settings.get('expose_internal_public_keys',False))
    elif profile=='consent-public':app=build_native_consent_public(settings['consent_public'],consent_engine=engine)
    else:raise ValueError('Unknown native administration service profile')
    allowed_posts={'/user-access/get_permissions_for_roles','/data-policies/evaluate_expression','/auth/start_authentication_transaction'} if profile=='iam' else set()
    if profile=='iam':
        allowed_posts.update(path for path in json.loads(Path(__file__).with_name('iam_console_permissions.json').read_text()) if path.rsplit('/',1)[-1].startswith('get_'))
        allowed_posts.add('/auth/backchannel-logout')
    @app.middleware('http')
    async def standby_admission(request,call_next):
        if not writable and request.method not in {'GET','HEAD','OPTIONS'} and request.url.path not in allowed_posts:
            return JSONResponse({'error':'Native administration standby; business writer ownership has not transferred'},status_code=503,headers={'cache-control':'no-store','retry-after':'5'})
        response=await call_next(request);response.headers['X-KarnatakaDBT-Native-Profile']=profile;return response
    @app.get('/health')
    def health():
        with engine.connect() as c:readonly=c.execute(text('SHOW transaction_read_only')).scalar_one()=='on'
        if readonly==writable:raise RuntimeError('Administration database credentials differ from configured writer mode')
        admitted=False
        if ownership:
            try:
                with ownership.admission('NATIVE'):admitted=True
            except ValueError:pass
        return {'ready':True,'profile':profile,'state':('NATIVE' if admitted else 'AWAITING_OWNERSHIP') if writable else 'STANDBY','business_writes_enabled':bool(writable and admitted),'writer_configured':writable,'database_read_only':readonly,'legacy_business_http_dependency':False}
    if ownership:app.add_middleware(AdministrationWriterAdmission,ownership=ownership)
    return app


if os.environ.get('KDBT_NATIVE_ADMIN_SETTINGS'):
    app=build(json.loads(Path(os.environ['KDBT_NATIVE_ADMIN_SETTINGS']).read_text()))
