"""Own partner REST API and console backed by the own transaction engine.

IAM is an explicit retained authentication dependency. Partner business requests
are handled locally; public keys are opt-in on an internal service surface.
"""
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
import httpx,jwt
from fastapi import Depends,FastAPI,Request,Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field,model_validator
from administration_console_gateway import AdministrationAuthority
from registry_console_ui import mount_registry_console
from registry_metadata_api import RegistryAuthError
from native_partner_engine import NativePartnerEngine,PartnerError
from native_partner_audit import PartnerAuditEmitter

class KeyInput(BaseModel):
    public_key:str|None=None
    jwk:dict|None=None
    kid:str|None=Field(None,max_length=255)
    algorithm:str|None=None
    not_before:datetime|None=None
    not_after:datetime|None=None
    @model_validator(mode='after')
    def one_source(self):
        if bool(self.public_key)==bool(self.jwk):raise ValueError('Provide exactly one public key source.')
        return self
class Onboarding(BaseModel):
    partner_id:str=Field(min_length=1,max_length=255)
    name:str=Field(min_length=1,max_length=255)
    org_name:str|None=Field(None,max_length=255)
    description:str|None=None
    jwks_url:str|None=Field(None,max_length=1024)
    keys:list[KeyInput]=Field(default_factory=list)
    import_from_jwks_url:bool=False
class KeyUpdate(BaseModel):
    partner_id:str=Field(min_length=1,max_length=255)
    description:str|None=None
    keys:list[KeyInput]=Field(default_factory=list)
    jwks_url:str|None=Field(None,max_length=1024)
    import_from_jwks_url:bool=False
    revoke_kids:list[str]=Field(default_factory=list)
class Review(BaseModel):notes:str|None=None

def create_native_partner_api(engine,iam_url,*,identity_transport=None,key_lookup=None,jwks_transport=None,jwks_http_origins=(),expose_internal_public_keys=False,key_fetch_cache_max_age=300,audit_config=None,audit_transport=None):
    if not isinstance(key_fetch_cache_max_age,int) or key_fetch_cache_max_age<0:raise ValueError('Explicit nonnegative key-cache duration required')
    origin='https://localhost:8448'
    authority=AdministrationAuthority('partner',iam_url,[origin],transport=identity_transport,key_lookup=key_lookup)
    store=NativePartnerEngine(engine);app=FastAPI(title='KarnatakaDBT native partner management');audit_emitter=PartnerAuditEmitter(**(audit_config or {}),transport=audit_transport)
    schemas=json.loads(Path(__file__).with_name('partner_console_contract.json').read_text())['components']['schemas']
    def view(kind,row):return {key:row.get(key) for key in schemas[kind]['properties']}
    async def authenticate(request:Request):
        principal=await authority(request)
        if 'role:partner_manager' not in principal.permissions:raise RegistryAuthError(403,'Assigned partner-manager access required')
        request.state.partner_actor_verified=True
        claims=jwt.decode(request.state.administration_bearer,options={'verify_signature':False})
        return {'id':principal.subject,'name':claims.get('preferred_username') or claims.get('email') or principal.subject}
    async def collect_import(data):
        if not data.import_from_jwks_url:return None
        if not data.jwks_url:raise PartnerError('PM-KEY-400','import_from_jwks_url is set but jwks_url is empty.')
        url=urlsplit(data.jwks_url);base=url.scheme+'://'+url.netloc
        if url.username or url.password or url.fragment or not url.hostname or (url.scheme!='https' and base not in jwks_http_origins):raise PartnerError('PM-JWK-502','An approved JWKS URL is required.')
        try:
            async with httpx.AsyncClient(timeout=5,trust_env=False,follow_redirects=False,transport=jwks_transport) as client:
                async with client.stream('GET',data.jwks_url) as response:
                    response.raise_for_status();body=b''
                    async for chunk in response.aiter_bytes():
                        body+=chunk
                        if len(body)>1024*1024:raise ValueError('JWKS exceeds limit')
                    value=json.loads(body)
            keys=value.get('keys')
            if not isinstance(keys,list) or not keys or not all(isinstance(key,dict) for key in keys):raise ValueError('Invalid JWKS')
            return keys
        except (httpx.HTTPError,ValueError,TypeError,AttributeError):raise PartnerError('PM-JWK-502','JWKS import failed.') from None
    @app.middleware('http')
    async def preserve_session(request,call_next):
        # Match the gateway's admission bound before parsing a request body.
        if request.method in {'POST','PUT','PATCH'}:
            body=bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body)>8*1024*1024:return JSONResponse({'error':'Partner request is too large'},status_code=413)
            request._body=bytes(body)
        result=await call_next(request)
        result.headers['cache-control']=('public, max-age='+str(key_fetch_cache_max_age)) if expose_internal_public_keys and request.url.path.startswith('/keys/') and result.status_code==200 else 'no-store'
        result.headers['x-content-type-options']='nosniff'
        for value in getattr(request.state,'registry_auth_cookies',[]):
            if value not in result.headers.get_list('set-cookie'):result.headers.append('set-cookie',value)
        audit_emitter.attach(request,result)
        return result
    @app.exception_handler(PartnerError)
    async def domain_error(request,error):return JSONResponse({'errors':[{'code':error.code,'message':error.message}]},status_code=error.status)
    @app.exception_handler(RegistryAuthError)
    async def auth_error(request,error):return JSONResponse({'error':error.message},status_code=error.status)
    mount_registry_console(app,iam_url,[origin],origin+'/console/',profile='partner',authorize=authority,identity_transport=identity_transport)
    @app.get('/ping')
    def ping():return {'status':'ok'}
    @app.post('/partners/requests/onboarding')
    async def onboarding(data:Onboarding,actor=Depends(authenticate)):
        imported=await collect_import(data);return view('PartnerRequestResponse',store.create('onboarding',data.model_dump(),actor,imported))
    @app.post('/partners/requests/key-update')
    async def key_update(data:KeyUpdate,actor=Depends(authenticate)):
        imported=await collect_import(data);return view('PartnerRequestResponse',store.create('key_update',data.model_dump(),actor,imported))
    @app.get('/partners/requests')
    def requests(status:str|None=None,partner_id:str|None=None,actor=Depends(authenticate)):
        values=[view('PartnerRequestResponse',row) for row in store.list('partner_requests',status=status,partner_id=partner_id)];return {'count':len(values),'requests':values}
    @app.get('/partners/requests/{request_id}')
    def request_details(request_id:str,actor=Depends(authenticate)):
        with engine.connect() as c:return view('PartnerRequestResponse',store.request(c,request_id))
    @app.post('/partners/requests/{request_id}/approve')
    def approve(request_id:str,review:Review=Review(),actor=Depends(authenticate)):return view('PartnerRequestResponse',store.decide(request_id,True,actor,review.notes))
    @app.post('/partners/requests/{request_id}/reject')
    def reject(request_id:str,review:Review=Review(),actor=Depends(authenticate)):return view('PartnerRequestResponse',store.decide(request_id,False,actor,review.notes))
    @app.get('/partners')
    def partners(status:str|None=None,actor=Depends(authenticate)):
        values=[view('PartnerResponse',row) for row in store.list('partners',status=status)];return {'count':len(values),'partners':values}
    @app.get('/partners/{partner_id}')
    def partner(partner_id:str,actor=Depends(authenticate)):
        with engine.connect() as c:return view('PartnerResponse',store.partner(c,partner_id))
    @app.get('/partners/{partner_id}/keys')
    def keys(partner_id:str,actor=Depends(authenticate)):return [view('KeyResponse',row) for row in store.list('partner_keys',partner_id=partner_id)]
    @app.get('/partners/{partner_id}/audit')
    def audit(partner_id:str,actor=Depends(authenticate)):
        values=[view('AuditEventResponse',row) for row in store.list('audit_events',partner_id=partner_id)];return {'count':len(values),'events':values}
    @app.post('/partners/{partner_id}/disable')
    def disable(partner_id:str,actor=Depends(authenticate)):
        row=store.set_status(partner_id,False,actor);return {'partner_id':row['partner_id'],'status':row['status'],'message':"Partner disabled. Key-fetch now returns 'not available'."}
    @app.post('/partners/{partner_id}/enable')
    def enable(partner_id:str,actor=Depends(authenticate)):
        row=store.set_status(partner_id,True,actor);return {'partner_id':row['partner_id'],'status':row['status'],'message':'Partner re-enabled. Active keys are served again.'}
    if expose_internal_public_keys:
        def public(partner_id):
            values=store.servable_keys(partner_id)
            if not values:raise PartnerError('PM-KEY-404',f"No keys available for partner '{partner_id}'.",404)
            return values
        @app.get('/keys/{partner_id}')
        def public_keys(partner_id:str):return {'partner_id':partner_id,'keys':public(partner_id)}
        @app.get('/keys/{partner_id}/jwks.json')
        def public_jwks(partner_id:str):return store.keys.jwks(public(partner_id))
        @app.get('/keys/{partner_id}/{kid}')
        def public_key(partner_id:str,kid:str):
            match=next((key for key in public(partner_id) if key['kid']==kid),None)
            if match is None:raise PartnerError('PM-KEY-404',f"No keys available for partner '{partner_id}'.",404)
            return match
    app.state.native_partner_engine=store;app.state.legacy_partner_business_api_retained=False;app.state.legacy_iam_retained=True
    return app
