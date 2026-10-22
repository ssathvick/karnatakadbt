"""Small HTTP client for the existing approval engine; no registry fallback."""
import math
from urllib.parse import quote,urlsplit,urlunsplit
import httpx
from registry_metadata_store import RegistryError

class ApprovalEngineClient:
    def __init__(self,base_url,transport=None,timeout=30):
        parts=urlsplit(base_url)
        if parts.scheme not in {'http','https'} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:raise ValueError('A configured approval-engine origin is required')
        path=parts.path.rstrip('/')
        if path.endswith('/v1/awe'):path=path[:-7]
        self.base_url=urlunsplit((parts.scheme,parts.netloc,path,'','')).rstrip('/');self.transport=transport;self.timeout=timeout
    def call(self,token,method,path,params=None,body=None,extra_headers=None):
        # Never retry a decision or follow a redirect carrying staff credentials.
        with httpx.Client(base_url=self.base_url,headers={'authorization':'Bearer '+token,'content-type':'application/json','accept':'application/json'},timeout=self.timeout,trust_env=False,transport=self.transport,follow_redirects=False) as client:
            response=client.request(method,path,params=params,json=body,headers=extra_headers) if body is not None else client.request(method,path,params=params,headers=extra_headers)
        if not response.is_success:
            try:
                value=response.json();code=value.get('errorCode','AWE-UNKNOWN');message=value.get('message') or value.get('detail') or response.text
            except Exception:code='AWE-UNKNOWN';message=response.text
            message=str(message)+' (url='+str(response.request.url)+')'
            if code=='AWE-007':raise RegistryError('AWE-007',message)
            raise RegistryError('AWE-ERR-006','AWE_REQUEST_FAILED: '+message)
        return response.json()
    def tasks(self,token,assignee='me',**filters):
        page=filters.pop('page',1);size=filters.pop('page_size',25)
        value=self.call(token,'GET','/v1/awe/tasks',params={'assignee':assignee,'page':page,'page_size':size,**{key:val for key,val in filters.items() if val is not None}})
        if isinstance(value,dict):return value
        if isinstance(value,list):return {'items':value,'total':len(value),'page':page,'page_size':size,'pages':math.ceil(len(value)/size) if value and size else 1}
        return {'items':[],'total':0,'page':page,'page_size':size,'pages':1}
    def request_tasks(self,token,request_id,page_size=100):
        everyone=self.tasks(token,'*',request_id=request_id,page=1,page_size=page_size);mine=self.tasks(token,'me',request_id=request_id,page=1,page_size=page_size)
        mine=list(mine.get('items') or []);ids={task['id'] for task in mine};sort=lambda task:(task.get('stage_order') or 0,task.get('created_at') or '')
        actionable=sorted([task for task in mine if task.get('status') in {'open','claimed'}],key=sort)
        others=sorted([task for task in everyone.get('items') or [] if task['id'] not in ids and task.get('status')=='completed' and task.get('decision_action')=='approve'],key=sort)
        items=(actionable[:1] if actionable else sorted(mine,key=sort))+others
        return {'items':items,'total':len(items),'page':1,'page_size':page_size,'pages':1}
    def resource(self,kind,key,suffix=''):
        # Resource identifiers are path segments, never caller-selected routes.
        if key in {'.','..'}:raise ValueError('Invalid approval resource identifier')
        return '/v1/awe/'+kind+'/'+quote(key,safe='')+suffix
