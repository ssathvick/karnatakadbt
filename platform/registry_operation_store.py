"""Own export queue projection and applied approval-event reconciliation."""
import datetime,hashlib,json
from functools import cached_property
from pathlib import Path
from sqlalchemy import MetaData,Table,Column,String,DateTime,BigInteger,Identity,Boolean,Index,select,func,insert
from sqlalchemy.dialects.postgresql import JSONB
from registry_decision_store import RegistryDecisionStore
from registry_record_store import record_timestamp
from registry_metadata_api import RegistryPrincipal

metadata=MetaData()
operations=Table('console_registry_operations',metadata,Column('kind',String,primary_key=True),Column('key',String,primary_key=True),Column('owner',String),Column('artifact_type',String),Column('artifact_id',String),Column('applied',Boolean),Column('at',DateTime),Column('received_at',DateTime),Column('sequence',BigInteger,Identity(),nullable=False),Column('data',JSONB,nullable=False))
Index('ix_console_operation_export_owner_time',operations.c.kind,operations.c.owner,operations.c.at)
Index('ix_console_operation_artifact_time',operations.c.kind,operations.c.artifact_type,operations.c.artifact_id,operations.c.applied,operations.c.at,operations.c.received_at)
EXPORT_PATH='/register-data/get_export_queue_records'
REJECT_PATH='/intake-form-data/reject_intake_form_submission'
SUPPORTED_PATHS=frozenset([EXPORT_PATH,REJECT_PATH])

class RegistryOperationStore(RegistryDecisionStore):
    def initialize(self):
        super().initialize();metadata.create_all(self.engine)
        for index in operations.indexes:index.create(self.engine,checkfirst=True)
    @cached_property
    def operation_contract(self):return json.loads(Path(__file__).with_name('registry_operation_contract.json').read_text())
    def operation_values(self,kind,value):
        meta=self.operation_contract[kind];key=hashlib.sha256(json.dumps([value[field] for field in meta['primary_key']],sort_keys=True).encode()).hexdigest()
        if set(value)-set(meta['selected_fields']):raise ValueError('Unexpected private operation field')
        def stamp(raw):
            if raw is None:return None
            value=record_timestamp(raw)
            return value.astimezone(datetime.timezone.utc).replace(tzinfo=None) if value is not None and value.tzinfo is not None else value
        return {'kind':kind,'key':key,'owner':value.get('requested_by'),'artifact_type':value.get('artifact_type'),'artifact_id':value.get('artifact_id'),'applied':value.get('applied'),'at':stamp(value.get('queued_at') if kind=='export' else value.get('occurred_at')),'received_at':stamp(value.get('received_at')),'data':value}
    def reconcile_summary(self,c,kind,value):
        if not value.get('awe_request_id'):return value
        artifact='registry.intake_form' if kind=='intake' else 'registry.change_request';field='submission_id' if kind=='intake' else 'change_request_id';summary=None;status=None;stage=None;profile=self.operation_contract['approval_summary']
        query=select(operations.c.data).where(operations.c.kind=='event',operations.c.artifact_type==artifact,operations.c.artifact_id==str(value[field]),operations.c.applied.is_(True)).order_by(operations.c.at,operations.c.received_at)
        for event in c.execute(query).scalars():
            incoming=event.get('status');event_type=event['event_type'];incoming_stage=event.get('stage_order')
            if event_type in profile['skip_event_types'] or not incoming:continue
            if status is None or profile['status_ranks'].get(incoming,-1)>=profile['status_ranks'].get(status,-1):status=incoming
            if incoming_stage is not None:
                if event_type=='stage_started' or stage is None or incoming_stage>=stage:stage=incoming_stage
            summary=status+('-stage'+str(stage) if stage is not None else '')
        if summary is not None and value.get('awe_request_status_summary')!=summary:
            value={**value,'awe_request_status_summary':summary};self.put_row(c,kind,value)
        return value
    def execute_request(self,path,p,actor,pagination=None):
        if path!=EXPORT_PATH:return super().execute_request(path,p,actor,pagination)
        if not actor:self.fail('INVALID_REQUEST','Authenticated user identifier is required')
        page=pagination or {};number=max(1,page.get('current_page') or 1);size=max(1,page.get('page_size') or 20);now=self.clock();cutoff=now-datetime.timedelta(days=max(1,self.operation_contract['export_visibility_days']))
        with self.engine.connect() as c:
            conditions=[operations.c.kind=='export',operations.c.owner==actor,operations.c.at>=cutoff];total=c.execute(select(func.count()).select_from(operations).where(*conditions)).scalar_one();query=select(operations.c.data).where(*conditions).order_by(operations.c.at.desc()).offset((number-1)*size).limit(size);result=[]
            fields=self.models.definitions['RegisterExportQueueData']['properties']
            for value in c.execute(query).scalars():
                item={field:value.get(field) for field in fields};expiry=record_timestamp(value['file_url_expires_at']) if value.get('file_url_expires_at') else None
                if value['export_status']!='COMPLETED' or expiry is not None and expiry<=now:item['file_presigned_url']=None
                result.append(self.models.model('RegisterExportQueueData').model_validate(item).model_dump(mode='json'))
            return result,{'number_of_items':total,'number_of_pages':(total+size-1)//size}
    def execute_policy_request(self,path,p,principal,pagination=None):
        if path!=REJECT_PATH:return super().execute_policy_request(path,p,principal,pagination)
        if not isinstance(principal,RegistryPrincipal):raise ValueError('Trusted intake decision principal required')
        with self.engine.begin() as c:
            value=self.intake_meta(c,p['submission_id'],lock=True);self.readable_submission(c,value['submission_id'],principal.data_policies)
            if value['approval_status']!='PENDING':self.fail('REQUEST_VALIDATION_ERROR',f"Submission '{value['submission_id']}' is already in approval_status '{value['approval_status']}'")
            stamp=self.clock();value.update(approval_status='REJECTED',approved_by=principal.name or 'Unknown',approved_at=stamp.isoformat(),last_updated_at=stamp.isoformat());self.put_row(c,'intake',value);value=self.reconcile_summary(c,'intake',value);sections=self.section_payloads(c,value,principal.data_policies);name=next((record['record_name'] for section in sections for record in section['records'] if record.get('record_name')),None);result=self.submission_payload(value,sections,name);self.record_decision(c,path,str(value['submission_id']),principal,stamp=stamp)
            return result,None
