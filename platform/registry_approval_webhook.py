"""Native HMAC callback, durable event deduplication and atomic decisions."""
import datetime,hashlib,hmac,json,time,uuid
from pydantic import BaseModel
from sqlalchemy import MetaData,Table,Column,String,select,insert,update,text
from sqlalchemy.dialects.postgresql import JSONB
from registry_approval_store import RegistryApprovalStore
from registry_row_store import rows
from registry_layout_store import layouts
from registry_operation_store import operations
from registry_record_store import record_timestamp
from registry_metadata_store import RegistryError
from registry_metadata_api import RegistryPrincipal,RegistryAuthError

WEBHOOK_PATH='/awe/webhooks/decision'
metadata=MetaData()
webhook_events=Table('console_registry_approval_events',metadata,Column('event_id',String,primary_key=True),Column('digest',String,nullable=False),Column('data',JSONB,nullable=False))

class ApprovalEvent(BaseModel):
    event_id:str
    event_type:str
    request_id:str
    artifact_type:str
    artifact_id:str
    status:str
    stage_order:int|None=None
    actor:str|None=None
    occurred_at:datetime.datetime

class RegistryApprovalWebhookStore(RegistryApprovalStore):
    def __init__(self,*args,webhook_settings=None,**kwargs):super().__init__(*args,**kwargs);self.webhook_settings=webhook_settings or {}
    def initialize(self):super().initialize();metadata.create_all(self.engine)
    def verify_webhook_signature(self,body,signature,timestamp):
        secret=(self.webhook_settings.get('hmac_secret') or '').strip()
        if not secret:raise RegistryAuthError(401,'AWE webhook HMAC secret is not configured')
        if not signature or not signature.startswith('sha256='):raise RegistryAuthError(401,'Missing or invalid X-Approval-Signature header')
        if not timestamp:raise RegistryAuthError(401,'Missing X-Approval-Timestamp header')
        try:stamp=int(timestamp)
        except ValueError:raise RegistryAuthError(401,'Invalid X-Approval-Timestamp header') from None
        if abs(int(time.time())-stamp)>int(self.webhook_settings.get('tolerance_seconds',300)):raise RegistryAuthError(401,'Webhook timestamp outside allowed skew window')
        expected=hmac.new(secret.encode(),(str(stamp)+'.').encode()+body,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,signature[7:]):raise RegistryAuthError(401,'Webhook signature mismatch')
    def resolve_webhook_artifact(self,c,event):
        intake=event.artifact_type=='registry.intake_form';kind='intake' if intake else 'change';field='submission_id' if intake else 'change_request_id'
        if event.artifact_type not in {'registry.intake_form','registry.change_request'}:self.fail('AWE_WEBHOOK_UNSUPPORTED_ARTIFACT','AWE_WEBHOOK_UNSUPPORTED_ARTIFACT: '+event.artifact_type)
        key=event.artifact_id;invalid=False
        if intake:
            try:key=str(uuid.UUID(key))
            except ValueError:invalid=True
        value=None if invalid else c.execute(select(rows.c.data).where(rows.c.kind==kind,rows.c.data[field].astext==key).with_for_update()).scalar_one_or_none()
        if value is None:value=c.execute(select(rows.c.data).where(rows.c.kind==kind,rows.c.data['awe_request_id'].astext==event.request_id).with_for_update()).scalar_one_or_none()
        if value is None:
            if not intake:self.fail('CHANGE_REQUEST_NOT_FOUND')
            if invalid:self.fail('REQUEST_VALIDATION_ERROR',f'REQUEST_VALIDATION_ERROR: artifact_id must be a valid UUID, got {event.artifact_id!r}')
            self.fail('INTAKE_FORM_NOT_FOUND',f'INTAKE_FORM_NOT_FOUND: artifact_id={key}, request_id={event.request_id}')
        if value.get('awe_request_id') and value['awe_request_id']!=event.request_id:self.fail('AWE_WEBHOOK_REQUEST_MISMATCH')
        return kind,dict(value)
    def webhook_terminal(self,c,event,kind,value):
        target={'request_approved':'APPROVED','request_rejected':'REJECTED','request_cancelled':'CANCELLED'}[event.event_type]
        if value['approval_status']==target:return
        if value['approval_status']!='PENDING':
            if kind=='change':self.fail('CHANGE_REQUEST_NOT_IN_PENDING_STATE')
            self.fail('REQUEST_VALIDATION_ERROR',f"Submission '{value['submission_id']}' is already in approval_status '{value['approval_status']}'")
        principal=RegistryPrincipal('awe:'+(event.actor or 'system'),frozenset(),event.actor or 'system')
        if kind=='change' and target=='APPROVED':
            change=self.approve_on_connection(c,value['change_request_id'],principal,skip_verification=True)
            section=c.execute(select(layouts.c.data).where(layouts.c.kind=='section',layouts.c.id==change['section_id'])).scalar_one()
            payload=c.execute(select(rows.c.data).where(rows.c.kind=='change-payload',rows.c.data['change_request_id'].astext==change['change_request_id'])).scalar_one()
            self.approval_score_jobs(c,change,section,payload['change_payload'],score_only=True)
            return
        stamp=self.clock();value.update(approval_status=target,approved_by=event.actor or 'system',approved_at=stamp.isoformat())
        if target=='REJECTED':value['remarks']='Rejected via AWE approval workflow'
        if kind=='intake':
            value['last_updated_at']=stamp.isoformat()
            if target=='APPROVED':value.update(register_ingest_process_status='PENDING',register_ingest_process_last_error_code=None)
        self.put_row(c,kind,value);self.record_decision(c,WEBHOOK_PATH,str(value['submission_id' if kind=='intake' else 'change_request_id']),principal,stamp=stamp)
    def save_webhook_event(self,c,event,digest,applied,error=None):
        existing=c.execute(select(webhook_events.c.data).where(webhook_events.c.event_id==event.event_id)).scalar_one_or_none()
        value=event.model_dump(mode='json');value.update(received_at=existing['received_at'] if existing else self.clock().isoformat(),applied=applied,error=error)
        if existing:c.execute(update(webhook_events).where(webhook_events.c.event_id==event.event_id).values(data=value))
        else:c.execute(insert(webhook_events).values(event_id=event.event_id,digest=digest,data=value))
        public={field:value.get(field) for field in self.operation_contract['event']['selected_fields']};attrs=self.operation_values('event',public)
        found=c.execute(select(operations.c.key).where(operations.c.kind=='event',operations.c.key==attrs['key'])).first()
        if found:c.execute(update(operations).where(operations.c.kind=='event',operations.c.key==attrs['key']).values(**attrs))
        else:c.execute(insert(operations).values(**attrs))
    def handle_approval_webhook(self,body,signature,timestamp,event_id=None):
        self.verify_webhook_signature(body,signature,timestamp)
        event=ApprovalEvent.model_validate_json(body)
        if event_id and event_id!=event.event_id:self.fail('AWE_WEBHOOK_EVENT_ID_MISMATCH')
        digest=hashlib.sha256(json.dumps(event.model_dump(mode='json'),sort_keys=True).encode()).hexdigest()
        # Serialize duplicates before looking at the event and lock its request
        # separately: two different terminal events must not race either.
        try:
            with self.engine.begin() as c:
                c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:event,0))'),{'event':'registry-webhook:'+event.event_id})
                existing=c.execute(select(webhook_events).where(webhook_events.c.event_id==event.event_id).with_for_update()).first()
                if existing:
                    if existing.digest!=digest:self.fail('AWE_WEBHOOK_EVENT_ID_MISMATCH')
                    if existing.data['applied']:return {'event_id':event.event_id,'applied':True,'message':'duplicate'}
                self.save_webhook_event(c,event,digest,False)
                kind,value=self.resolve_webhook_artifact(c,event)
                if event.event_type in {'request_approved','request_rejected','request_cancelled'}:self.webhook_terminal(c,event,kind,value)
                self.save_webhook_event(c,event,digest,True)
                if event.event_type not in {'request_approved','request_rejected'}:
                    refreshed=c.execute(select(rows.c.data).where(rows.c.kind==kind,rows.c.key==self.row_key(kind,value))).scalar_one()
                    self.reconcile_summary(c,kind,refreshed)
            return {'event_id':event.event_id,'applied':True,'message':'ok'}
        except Exception as error:
            # Failed business writes are rolled back first. Retain a separate
            # retry journal without persisting beneficiary-bearing SQL errors.
            with self.engine.begin() as c:
                c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:event,0))'),{'event':'registry-webhook:'+event.event_id})
                existing=c.execute(select(webhook_events).where(webhook_events.c.event_id==event.event_id)).first()
                if not existing or existing.digest==digest and not existing.data['applied']:
                    self.save_webhook_event(c,event,digest,False,getattr(error,'code','PROCESSING_FAILED'))
            raise
