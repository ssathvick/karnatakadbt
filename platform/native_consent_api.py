"""Native consent STAFF API: policies, signed callbacks and approval adapters.

Public lifecycle, subject and consent-validation APIs are not mounted here.
Identity remains live IAM/Keycloak; approval calls target a fixed configured
service and carry either the acting staff token or explicit service credentials.
"""
import json
from pathlib import Path
from urllib.parse import quote,urlsplit
import httpx
from fastapi import Depends,FastAPI,Query,Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field
from sqlalchemy.exc import SQLAlchemyError
from administration_console_gateway import AdministrationAuthority
from registry_console_ui import mount_registry_console
from registry_metadata_api import RegistryAuthError
from native_consent_policy import NativeConsentPolicy,ConsentPolicyError
from consent_console_routes import mount_staff_routes
class BindingCreate(BaseModel):
    partner_mgmt_id:str|None=Field(None,max_length=255)
    audience:str=Field(min_length=1,max_length=255)
    controller_id:str=Field(min_length=1,max_length=255)
    name:str|None=Field(None,max_length=255)
class BindingUpdate(BaseModel):
    name:str|None=None
    status:str|None=None
    partner_mgmt_id:str|None=None
class PolicyInput(BaseModel):
    allowed_data_scopes:list[str]=Field(default_factory=list)
    allowed_purposes:list[str]=Field(default_factory=list)
    allowed_subject_id_types:list[str]=Field(default_factory=list)
    allowed_signing_algs:list[str]=Field(default_factory=lambda:['EdDSA','ES256'])
    max_validity_duration:str|None=None
    fetch_type:str='oneshot'
    max_fetch_frequency:str|None=None
    data_life:str|None=None
class DecisionInput(BaseModel):
    action:str
    comment:str|None=None

def create_native_consent_api(engine,iam_url,*,approval_url=None,approval_enabled=False,service_token=None,policy_key=None,callback_url=None,callback_secret_id=None,callback_secret=None,identity_transport=None,key_lookup=None,approval_transport=None,submission_outbox=None):
    if approval_url:
        parsed=urlsplit(approval_url)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'','/'}:raise ValueError('Explicit approval service origin required')
    origin='https://localhost:8449';authority=AdministrationAuthority('consent',iam_url,[origin],transport=identity_transport,key_lookup=key_lookup)
    if submission_outbox and (not approval_enabled or submission_outbox.policy_key!=policy_key or submission_outbox.callback_url!=callback_url or submission_outbox.callback_secret_id!=callback_secret_id):raise ValueError('Consent approval outbox configuration differs')
    store=NativeConsentPolicy(engine,approval_enabled=approval_enabled,callback_secret=callback_secret,submission_outbox=submission_outbox);app=FastAPI(title='KarnatakaDBT native consent staff API')
    schemas=json.loads(Path(__file__).with_name('consent_console_contract.json').read_text())['components']['schemas']
    def view(kind,row):return {key:row.get(key) for key in schemas[kind]['properties']}
    def require(role):
        async def check(request:Request):
            principal=await authority(request)
            if 'role:'+role not in principal.permissions:raise RegistryAuthError(403,'Assigned consent role required')
            return principal
        return check
    admin=require('CONSENT_MANAGER_ADMIN');approver=require('CONSENT_MANAGER_APPROVER')
    async def call(token,method,path,*,params=None,body=None,headers=None):
        if not approval_url:raise ConsentPolicyError(500,'awe_base_url is not configured')
        try:
            async with httpx.AsyncClient(timeout=15,trust_env=False,follow_redirects=False,transport=approval_transport) as client:
                result=await client.request(method,approval_url.rstrip('/')+path,params=params,json=body,headers={'authorization':'Bearer '+token,**(headers or {})})
        except httpx.HTTPError:raise ConsentPolicyError(502,'Approval service unavailable') from None
        if not result.is_success:
            try:message=result.json().get('message') or result.json().get('detail') or 'Approval request failed'
            except (ValueError,AttributeError):message='Approval request failed'
            raise ConsentPolicyError(result.status_code if 400<=result.status_code<600 else 502,str(message))
        try:return result.json()
        except ValueError:return {}
    def resource(kind,identifier,suffix=''):
        if identifier in {'.','..'} or '/' in identifier or '\\' in identifier:raise ConsentPolicyError(400,'Invalid approval resource identifier')
        return '/v1/awe/'+kind+'/'+quote(identifier,safe='')+suffix
    @app.middleware('http')
    async def boundary(request,call_next):
        if request.method in {'POST','PUT','PATCH'}:
            body=bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body)>8*1024*1024:return JSONResponse({'error':'Consent request is too large'},status_code=413)
            request._body=bytes(body)
        result=await call_next(request);result.headers['cache-control']='no-store';result.headers['x-content-type-options']='nosniff'
        for value in getattr(request.state,'registry_auth_cookies',[]):
            if value not in result.headers.get_list('set-cookie'):result.headers.append('set-cookie',value)
        return result
    @app.exception_handler(RegistryAuthError)
    async def auth_error(request,error):return JSONResponse({'error':error.message},status_code=error.status)
    @app.exception_handler(ConsentPolicyError)
    async def domain_error(request,error):return JSONResponse({'error':error.message},status_code=error.status)
    @app.exception_handler(SQLAlchemyError)
    async def persistence_error(request,error):return JSONResponse({'error':'Consent persistence unavailable'},status_code=503,headers={'cache-control':'no-store'})
    mount_registry_console(app,iam_url,[origin],origin+'/console/',profile='consent',authorize=authority,identity_transport=identity_transport)
    @app.get('/ping')
    def ping():return {'status':'ok'}
    @app.get('/consent/v1/partners')
    def bindings(controller_id:str|None=None,status:str|None=None,identity=Depends(admin)):return [view('PartnerResponse',row) for row in store.bindings(controller_id,status)]
    @app.post('/consent/v1/partners',status_code=201)
    def create_binding(data:BindingCreate,identity=Depends(admin)):return view('PartnerResponse',store.create_binding(data.model_dump()))
    @app.get('/consent/v1/partners/{partner_id}')
    def binding(partner_id:str,identity=Depends(admin)):
        row=store.binding(partner_id)
        if row is None:raise ConsentPolicyError(404,'not_found')
        return view('PartnerResponse',row)
    @app.patch('/consent/v1/partners/{partner_id}')
    def update_binding(partner_id:str,data:BindingUpdate,identity=Depends(admin)):
        row=store.update_binding(partner_id,data.model_dump())
        if row is None:raise ConsentPolicyError(404,'not_found')
        return view('PartnerResponse',row)
    @app.put('/consent/v1/partners/{partner_id}/policy')
    async def upsert(partner_id:str,data:PolicyInput,identity=Depends(admin)):
        partner=store.binding(partner_id)
        if partner is None:raise ConsentPolicyError(404,'not_found')
        policy=store.upsert_policy(partner_id,data.model_dump())
        if policy['status']=='pending':
            try:
                if not service_token or not policy_key:raise ConsentPolicyError(500,'Approval service credentials and policy are required')
                if submission_outbox:
                    request_id=await submission_outbox.deliver(policy['id'],service_token,call)
                    policy['awe_request_id']=request_id
                    return view('PolicyResponse',policy)
                token=await service_token()
                if not isinstance(token,str) or not token:raise ConsentPolicyError(500,'Approval service credential unavailable')
                context={'partner_label':partner['name'] or partner['partner_mgmt_id'] or partner['audience'],'partner_mgmt_id':partner['partner_mgmt_id'],'controller_id':partner['controller_id'],'policy_version':policy['version'],'allowed_data_scopes':policy['allowed_data_scopes'],'allowed_purposes':policy['allowed_purposes']}
                result=await call(token,'POST','/v1/awe/requests',body={'policy_key':policy_key,'artifact_type':'consent_manager.policy_change','artifact_id':policy['id'],'context':context,'callback_url':callback_url or None,'callback_secret_id':callback_secret_id or None,'requester':None},headers={'Idempotency-Key':'cm-partner-'+policy['id']})
                request_id=result.get('request_id') if isinstance(result,dict) else None
                if not isinstance(request_id,str) or not request_id:raise ConsentPolicyError(502,'Approval response missing request_id')
                store.set_request(policy['id'],request_id);policy['awe_request_id']=request_id
            except ConsentPolicyError as error:return JSONResponse({'error':'awe_submit_failed','message':error.message,'policy_id':policy['id']},status_code=502)
        return view('PolicyResponse',policy)
    @app.get('/consent/v1/partners/{partner_id}/policy')
    def policy(partner_id:str,version:int|None=None,identity=Depends(admin)):
        row=store.policy(partner_id,version)
        if row is None:raise ConsentPolicyError(404,'not_found')
        return view('PolicyResponse',row)
    @app.get('/consent/v1/partners/{partner_id}/policies')
    def policies(partner_id:str,identity=Depends(admin)):
        rows=store.policies(partner_id)
        if rows is None:raise ConsentPolicyError(404,'not_found')
        return [view('PolicyResponse',row) for row in rows]
    @app.get('/consent/v1/decisions')
    def decisions(partner_id:str|None=None,decision:str|None=None,limit:int=Query(50,ge=1,le=200),identity=Depends(admin)):return [view('DecisionLogResponse',row) for row in store.decisions(partner_id,decision,limit)]
    @app.get('/consent/v1/awe/tasks')
    async def tasks(request:Request,status:str|None='open',artifact_type:str|None='consent_manager.policy_change',page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),identity=Depends(approver)):
        return await call(request.state.administration_bearer,'GET','/v1/awe/tasks',params={'assignee':'me','page':page,'page_size':page_size,**({'status':status} if status else {}),**({'artifact_type':artifact_type} if artifact_type else {})})
    @app.post('/consent/v1/awe/tasks/{task_id}/claim')
    async def claim(task_id:str,request:Request,identity=Depends(approver)):return await call(request.state.administration_bearer,'POST',resource('tasks',task_id,'/claim'))
    @app.post('/consent/v1/awe/tasks/{task_id}/decision')
    async def decide(task_id:str,data:DecisionInput,request:Request,identity=Depends(approver)):return await call(request.state.administration_bearer,'POST',resource('tasks',task_id,'/decision'),body=data.model_dump())
    @app.get('/consent/v1/awe/requests/{request_id}')
    async def approval_request(request_id:str,request:Request,identity=Depends(approver)):return await call(request.state.administration_bearer,'GET',resource('requests',request_id))
    @app.get('/consent/v1/awe/requests/{request_id}/events')
    async def approval_events(request_id:str,request:Request,identity=Depends(approver)):return await call(request.state.administration_bearer,'GET',resource('requests',request_id,'/events'))
    @app.post('/consent/v1/awe/webhooks/decision')
    async def callback(request:Request):
        raw=await request.body();store.verify_signature(raw,request.headers.get('x-approval-timestamp'),request.headers.get('x-approval-signature'))
        try:event=json.loads(raw) if raw else {}
        except (ValueError,UnicodeDecodeError):raise ConsentPolicyError(400,'invalid_json') from None
        if not isinstance(event,dict):raise ConsentPolicyError(400,'invalid_json')
        return {'status':store.process_event(request.headers.get('x-approval-event-id'),event)}
    mount_staff_routes(app)
    app.state.native_consent_policy=store;app.state.legacy_consent_staff_business_api_retained=False;app.state.other_consent_apis_retained=True
    return app
