"""Expose the assembled native IAM staff application with the same live sessions."""
import json,os
import httpx
from urllib.parse import urlsplit
import redis
from sqlalchemy import text
from pathlib import Path
from fastapi.responses import RedirectResponse,JSONResponse
from fastapi import HTTPException
from native_administration_service import build

def create(settings):
    if settings['profile']!='iam':raise ValueError('Native IAM configuration required')
    parent=build(settings);app=parent.state.staff_application
    cache=redis.from_url(settings['auth']['auth_redis_url'],socket_timeout=5,socket_connect_timeout=5)
    aliases={'/auth/get_user_profile':'/api/me','/auth/logout':'/api/logout','/user-access/get_staff_portal_applications':'/api/applications'}
    for route in parent.routes:
        if route.path in aliases:app.add_api_route(aliases[route.path],route.endpoint,methods=['GET'],include_in_schema=False)
    @app.get('/api/login')
    async def legacy_login(redirect_uri:str|None=None):
        if redirect_uri is None:return RedirectResponse('/console/login',status_code=303)
        try:target=urlsplit(redirect_uri)
        except ValueError:raise HTTPException(400,'Staff return URL is not allowed') from None
        if target.scheme!='https' or target.netloc!='localhost:8451' or target.username or target.password or any(ord(ch)<32 or ch=='\\' for ch in redirect_uri):raise HTTPException(400,'Staff return URL is not allowed')
        try:
            async with httpx.AsyncClient(trust_env=False,timeout=10) as http:
                response=await http.post(settings['native_iam_url'].rstrip('/')+'/auth/start_authentication_transaction',params={'id':1,'redirect_uri':redirect_uri});response.raise_for_status();location=response.json()['redirectUrl']
            identity=urlsplit(location)
            if identity.scheme!='https' or identity.netloc!='localhost:8444' or not identity.path.startswith('/realms/staff/protocol/openid-connect/auth'):raise ValueError('Identity redirect is not allowed')
            result=RedirectResponse(location,status_code=303)
            for cookie in response.headers.get_list('set-cookie'):result.headers.append('set-cookie',cookie)
            return result
        except (httpx.HTTPError,ValueError,KeyError,TypeError):raise HTTPException(503,'Staff sign-in is temporarily unavailable') from None
    @app.middleware('http')
    async def identify(request,call_next):
        response=await call_next(request);response.headers['X-KarnatakaDBT-Native-Profile']='staff';return response
    @app.get('/')
    def root():return RedirectResponse('/console/',status_code=303)
    def locale_home(locale):
        def handle():return RedirectResponse('/console/?lang='+locale,status_code=303)
        return handle
    for locale in ['en','de','cs']:
        for suffix in ['', '/']:app.add_api_route('/'+locale+suffix,locale_home(locale),methods=['GET'])
    @app.get('/health')
    def health():
        with parent.state.native_access_store.engine.connect() as c:
            c.execute(text('SELECT 1'));readonly=c.execute(text('SHOW transaction_read_only')).scalar_one()=='on'
        if (not readonly and os.environ.get('KDBT_DEPLOYMENT_MODE')!='local') or not cache.ping():raise HTTPException(503,'Native staff dependencies unavailable')
        return {'ready':True,'native_staff_application':True,'legacy_business_http_dependency':False,'business_writes_enabled':False,'database_read_only':readonly,'session_store_ready':True}
    return app

if os.environ.get('KDBT_NATIVE_STAFF_SETTINGS'):app=create(json.loads(Path(os.environ['KDBT_NATIVE_STAFF_SETTINGS']).read_text()))
