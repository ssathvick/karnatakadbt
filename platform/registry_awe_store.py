"""Registry approval-console operations over own state and the engine HTTP API."""
import re,uuid
from pydantic import Field,create_model
from sqlalchemy import select
from registry_dedup_result_store import RegistryDedupResultStore
from registry_route_auth import AWE_PATHS
from registry_metadata_api import RegistryPrincipal,RegistryAuthError
from registry_row_store import rows

SUPPORTED_PATHS=AWE_PATHS|{'/change-requests/add_verification_for_change_request'}
PAYLOAD_MODELS={'list_my_tasks':'ListMyAweTasksRequestPayload','list_tasks_for_request':'ListTasksForRequestRequestPayload','my_task_stats':'MyAweTaskStatsRequestPayload','submit_task_decision':'SubmitAweTaskDecisionRequestPayload','claim_task':'ClaimAweTaskRequestPayload','get_request':'GetAweRequestRequestPayload','get_request_events':'GetAweRequestEventsRequestPayload'}

class RegistryAweStore(RegistryDedupResultStore):
    def __init__(self,engine,storage=None,clock=None,awe_client=None):
        super().__init__(engine,storage,clock);self.awe_client=awe_client
    def execute_request(self,path,p,actor,pagination=None):
        if path=='/change-requests/add_verification_for_change_request':return super().execute_request('/verifications/add_verification',p,actor,pagination)
        return super().execute_request(path,p,actor,pagination)
    def resolve_awe_payload(self,op,envelope):
        base=self.models.model(PAYLOAD_MODELS[op]);allowed=set(base.model_fields)
        merged={key:value for key,value in envelope.items() if key in allowed and value is not None}
        merged.update({key:value for key,value in (envelope.get('request_payload') or {}).items() if value is not None})
        model=base
        if op=='list_my_tasks':model=create_model('ResolvedMyApprovalTasks',__base__=base,search_text=(str|None,None),page=(int,1),page_size=(int,25))
        elif op=='list_tasks_for_request':model=create_model('ResolvedRequestApprovalTasks',__base__=base,page_size=(int,Field(100,ge=1,le=100)))
        for key,target in [('current_page','page'),('page_size','page_size'),('search_text','search_text')]:
            value=(envelope.get('pagination_request') or {}).get(key)
            if target in model.model_fields and value is not None:merged[target]=value
        return model.model_validate(merged).model_dump(mode='json')
    def validate_decision(self,p):
        kind={'registry.change_request':'change','registry.intake_form':'intake'}.get(p['artifact_type'])
        if kind is None:self.fail('AWE_WEBHOOK_UNSUPPORTED_ARTIFACT','AWE_WEBHOOK_UNSUPPORTED_ARTIFACT: '+p['artifact_type'])
        key=p['artifact_id'];field='change_request_id' if kind=='change' else 'submission_id'
        if kind=='intake':key=str(uuid.UUID(key))
        with self.engine.connect() as c:
            value=c.execute(select(rows.c.data).where(rows.c.kind==kind,rows.c.key==self.row_key(kind,{field:key}))).scalar_one_or_none()
        if value is None:self.fail('CHANGE_REQUEST_NOT_FOUND' if kind=='change' else 'INTAKE_FORM_NOT_FOUND')
        status=value.get('approval_status')
        if status in {'APPROVED','REJECTED'}:self.fail('AWE_INVALID_STATE_TRANSITION',f"Record is already '{status}' — cannot decide")
        if not value.get('awe_request_id'):self.fail('AWE_WEBHOOK_UNSUPPORTED_ARTIFACT',f"AWE_WEBHOOK_UNSUPPORTED_ARTIFACT: no AWE request for artifact {p['artifact_type']}/{p['artifact_id']}")
        match=re.match(r'^(.+)-stage(\d+)$',(value.get('awe_request_status_summary') or '').strip());stage=int(match[2]) if match else None
        if stage is not None and stage>p['current_stage']:self.fail('AWE_INVALID_STATE_TRANSITION',f"Request advanced to stage {stage} — cannot decide on stage {p['current_stage']}")
        if kind=='change' and p['action']=='approve':
            check=self.execute_request('/change-requests/check_change_request_sequence',{'change_request_id':key},'approval-check')[0]
            if check['approval_decision_blocked']:self.fail('REQUEST_VALIDATION_ERROR','There are earlier pending change requests for this record')
    def execute_awe_request(self,path,envelope,principal):
        if path not in AWE_PATHS or not isinstance(principal,RegistryPrincipal):raise ValueError('A trusted authenticated approval principal is required')
        token=principal.bearer_token
        if not token:self.fail('AWE_BEARER_TOKEN_REQUIRED')
        if self.awe_client is None:raise RegistryAuthError(503,'Approval engine is not configured')
        op=path.rsplit('/',1)[-1];p=self.resolve_awe_payload(op,envelope);client=self.awe_client
        if op=='list_my_tasks':value=client.tasks(token,**p)
        elif op=='list_tasks_for_request':value=client.request_tasks(token,**p)
        elif op=='my_task_stats':value=client.call(token,'GET','/v1/awe/tasks/stats',params={key:val for key,val in p.items() if val is not None})
        elif op in {'get_request','get_request_events'}:value=client.call(token,'GET',client.resource('requests',p['request_id'],'/events' if op=='get_request_events' else ''))
        elif op=='claim_task':value=client.call(token,'POST',client.resource('tasks',p['task_id'],'/claim'))
        else:
            self.validate_decision(p)
            if p['action'] not in {'approve','reject','abstain'}:raise ValueError('Invalid approval action')
            value=client.call(token,'POST',client.resource('tasks',p['task_id'],'/decision'),body={key:p[key] for key in ['action','comment','attachments_ref'] if p.get(key) is not None})
        return value if op=='get_request_events' else {'data':value},None
