"""Staff-only farmer console/API using authoritative IAM and explicit permissions."""
import inspect,json,os
from pathlib import Path
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse,FileResponse
from sqlalchemy import create_engine,text
from sqlalchemy.exc import IntegrityError
from native_farmer_registry import FarmerRegistry
from registry_console_auth import RegistryConsoleAuthorizer
from registry_metadata_api import RegistryAuthError

READ='farmerRegistry:view'
WRITE='farmerRegistry:edit'

def build(settings,*,authorize=None):
    engine=create_engine(settings['database_url'],hide_parameters=True,pool_pre_ping=True)
    store=FarmerRegistry(engine)
    authority=authorize or RegistryConsoleAuthorizer(settings['native_iam_url'],client_id='register-staff-portal',allowed_origins=settings['allowed_origins'])
    app=FastAPI(title='KarnatakaDBT dedicated farmer registry',docs_url=None,redoc_url=None,openapi_url=None)
    @app.middleware('http')
    async def protect(request,call_next):
        try:
            if request.url.path.startswith('/farmers/api/'):
                principal=authority(request)
                if inspect.isawaitable(principal):principal=await principal
                required={READ,WRITE} if request.method not in {'GET','HEAD'} else {READ}
                if not required.issubset(principal.permissions):raise RegistryAuthError(403,'Assigned farmer registry permission required')
                request.state.farmer_principal=principal
            result=await call_next(request)
        except RegistryAuthError as error:result=JSONResponse({'error':error.message},status_code=error.status)
        result.headers['cache-control']='no-store';result.headers['x-content-type-options']='nosniff';result.headers['referrer-policy']='no-referrer'
        result.headers['content-security-policy']="default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'"
        for cookie in getattr(request.state,'registry_auth_cookies',[]):result.headers.append('set-cookie',cookie)
        return result
    @app.get('/health')
    def health():
        with engine.connect() as c:c.execute(text('SELECT 1 FROM kdbt_farmer_registry.records LIMIT 1'))
        return {'ready':True,'domain':'FARMER','legacy_registry_dependency':False}
    @app.get('/farmers/')
    def home():return FileResponse(Path(__file__).with_name('farmer-console')/'index.html')
    @app.get('/farmers/app.js')
    def javascript():return FileResponse(Path(__file__).with_name('farmer-console')/'app.js',media_type='text/javascript')
    @app.get('/farmers/style.css')
    def stylesheet():return FileResponse(Path(__file__).with_name('farmer-console')/'style.css',media_type='text/css')
    @app.get('/farmers/api/session')
    def session(request:Request):return {'name':request.state.farmer_principal.name,'can_edit':WRITE in request.state.farmer_principal.permissions}
    @app.get('/farmers/api/records')
    def listing(offset:int=0,limit:int=25):
        try:return {'records':store.list(offset=offset,limit=limit)}
        except ValueError:return JSONResponse({'error':'Invalid pagination'},status_code=400)
    @app.get('/farmers/api/records/{identifier}')
    def record(identifier:str):
        result=store.get(identifier)
        return result if result else JSONResponse({'error':'Farmer not found'},status_code=404)
    @app.get('/farmers/api/records/{identifier}/history')
    def revisions(identifier:str):return {'revisions':store.revisions(identifier)}
    @app.put('/farmers/api/records/{identifier}')
    async def save(identifier:str,request:Request):
        try:
            body=b''
            async for chunk in request.stream():
                body+=chunk
                if len(body)>16384:return JSONResponse({'error':'Record too large'},status_code=413)
            value=json.loads(body)
            if not isinstance(value,dict) or set(value)!={'data','expected_revision'}:raise ValueError('Record and expected revision required')
            revision=store.save(identifier,value['data'],actor=request.state.farmer_principal.subject,expected_revision=value['expected_revision'])
            return {'farmer_id':identifier,'revision':revision}
        except IntegrityError:return JSONResponse({'error':'Farmer identifier already exists'},status_code=409)
        except (ValueError,KeyError,TypeError) as error:return JSONResponse({'error':'Farmer revision conflict' if str(error)=='Farmer revision conflict' else 'Invalid farmer record'},status_code=409 if str(error)=='Farmer revision conflict' else 400)
    return app

if os.environ.get('KDBT_NATIVE_FARMER_SETTINGS'):app=build(json.loads(Path(os.environ['KDBT_NATIVE_FARMER_SETTINGS']).read_text()))
