"""Own nonblocking central audit transport, without business payloads or tokens."""
import logging,uuid
from datetime import datetime,timezone
from urllib.parse import urlsplit
import httpx,jwt
from starlette.background import BackgroundTasks
ROUTE_NAMES={'onboarding':'create_onboarding','key_update':'create_key_update','requests':'list_requests','request_details':'get_request','approve':'approve_request','reject':'reject_request','partners':'list_partners','partner':'get_partner','keys':'list_partner_keys','audit':'partner_audit','disable':'disable_partner','enable':'enable_partner'}
class PartnerAuditEmitter:
    def __init__(self,*,url='',enabled=False,source='/karnatakadbt/partner-management',module='partner-management',client_id='commons-services-staff-portal',event_type_prefix='org.openg2p',audit_anonymous_failures=True,timeout_seconds=2,transport=None):
        parsed=urlsplit(url)
        if enabled and (parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment):raise ValueError('Explicit audit service origin required')
        self.enabled=bool(enabled and url);self.url=url.rstrip('/')+'/v1/auditmanager/events';self.source=source;self.module=module;self.client_id=client_id;self.type_prefix=event_type_prefix
        self.anonymous_failures=audit_anonymous_failures;self.timeout=timeout_seconds;self.transport=transport
    def event(self,request,status):
        if request.method=='OPTIONS' or request.url.path in {'/ping','/docs','/redoc','/openapi.json','/favicon.ico'} or request.url.path.startswith('/console/'):return None
        bearer=request.headers.get('authorization','');claims=None
        token=bearer[7:].strip() if bearer.lower().startswith('bearer ') else getattr(request.state,'administration_bearer',None)
        if token:
            try:claims=jwt.decode(token,options={'verify_signature':False})
            except Exception:pass
        if claims is None and not(self.anonymous_failures and status>=400):return None
        ip=request.headers.get('x-forwarded-for','').split(',')[0].strip() or request.headers.get('x-real-ip') or (request.client.host if request.client else None)
        if claims is not None:
            roles=set((claims.get('realm_access') or {}).get('roles') or []);roles.update((((claims.get('resource_access') or {}).get(self.client_id) or {}).get('roles') or []))
            actor={'type':'user','id':claims.get('sub') or 'unknown','name':claims.get('name'),'username':claims.get('preferred_username'),'roles':sorted(roles),'ip':ip,'session_id':claims.get('sid') or claims.get('session_state'),'identity_verified':bool(getattr(request.state,'partner_actor_verified',False))}
        else:actor={'type':'anonymous','id':'anonymous','ip':ip,'identity_verified':False}
        route=getattr(request.scope.get('route'),'name','') or request.url.path;route=ROUTE_NAMES.get(route,route)
        return {'specversion':'1.0','id':str(uuid.uuid4()),'source':self.source,'type':self.type_prefix+'.'+self.module+'.'+route,'time':datetime.now(timezone.utc).isoformat(),'datacontenttype':'application/json','data':{'actor':actor,'action':route.split('_')[0] if route else request.method.lower(),'outcome':'success' if status<400 else 'denied' if status in {401,403} else 'failure','context':{'api':request.method+' '+request.url.path,'module':self.module,'http_status':status,'request_id':request.headers.get('x-request-id')}}}
    async def send(self,event):
        try:
            async with httpx.AsyncClient(timeout=self.timeout,trust_env=False,follow_redirects=False,transport=self.transport) as client:
                response=await client.post(self.url,json=event);response.raise_for_status()
        except Exception:
            # Log neither URLs nor exception strings, which may contain tokens
            # or identifiers. Audit transport failure never undoes business data.
            logging.getLogger('karnatakadbt.partner.audit').warning('Central partner audit delivery failed')
    def attach(self,request,response):
        if not self.enabled:return
        try:event=self.event(request,response.status_code)
        except Exception:
            logging.getLogger('karnatakadbt.partner.audit').warning('Central partner audit event could not be constructed');return
        if event is None:return
        response.headers['X-KarnatakaDBT-Audit-Event-Id']=event['id']
        pending=BackgroundTasks()
        if response.background:pending.add_task(response.background)
        pending.add_task(self.send,event);response.background=pending
