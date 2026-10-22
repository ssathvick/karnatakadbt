"""Own finalization and export admission; engine and workers remain separate."""
import json,uuid
from functools import cached_property
from pathlib import Path
from sqlalchemy import MetaData,Table,Column,String,DateTime,Index,select,insert
from sqlalchemy.dialects.postgresql import JSONB
from registry_admission_store import RegistryAdmissionStore
from registry_operation_store import operations
from registry_configuration_store import configurations
from registry_metadata_api import RegistryPrincipal,RegistryAuthError
from registry_metadata_store import RegistryError

metadata=MetaData()
exports=Table('console_registry_export_queue',metadata,Column('id',String,primary_key=True),Column('owner',String,nullable=False),Column('status',String,nullable=False),Column('queued_at',DateTime,nullable=False),Column('data',JSONB,nullable=False))
Index('ix_console_export_pending_time',exports.c.status,exports.c.queued_at)
Index('ix_console_export_owner_time',exports.c.owner,exports.c.queued_at)
FINALIZE_PATH='/intake-form-data/finalize_intake_form_submission'
EXPORT_PATH='/register-data/export_register_records'
SUPPORTED_PATHS=frozenset([FINALIZE_PATH,EXPORT_PATH])

class RegistryWorkflowStore(RegistryAdmissionStore):
    def __init__(self,engine,storage=None,clock=None,awe_client=None,workflow_settings=None):
        super().__init__(engine,storage,clock,awe_client);self.workflow_settings=workflow_settings
    def initialize(self):
        super().initialize();metadata.create_all(self.engine)
        for index in exports.indexes:index.create(self.engine,checkfirst=True)
    @cached_property
    def workflow_contract(self):return json.loads(Path(__file__).with_name('registry_workflow_contract.json').read_text())
    def effective_workflow_policy(self,c,register,kind,section=None,form=None):
        types=self.workflow_contract['policy_types'][kind];base=[configurations.c.kind=='awe',configurations.c.data['register_id'].as_string()==register,configurations.c.data['policy_type'].as_string().in_(types)]
        scopes=[]
        if section:scopes.append(('SECTION','section_id',section))
        if form:scopes.append(('INTAKE_FORM','intake_form_id',form))
        scopes.append(('REGISTER',None,None))
        for scope,field,key in scopes:
            query=select(configurations.c.data).where(*base,configurations.c.data['policy_scope'].as_string()==scope)
            if field:query=query.where(configurations.c.data[field].as_string()==key)
            values=list(c.execute(query).scalars())
            if len(values)>1:raise RegistryError('SYS-ERR-001')
            if values:return values[0]
        return None
    def start_workflow(self,c,kind,value,principal,base,source_data):
        if not self.workflow_contract['awe_enabled']:return value
        policy=self.effective_workflow_policy(c,value['register_id'],kind,section=value.get('section_id') if kind=='change' else None,form=value.get('form_id') if kind=='intake' else None)
        if policy is None:return value
        token=(principal.bearer_token or '').strip()
        if not token:self.fail('AWE_BEARER_TOKEN_REQUIRED')
        if self.workflow_settings is None or self.awe_client is None:raise RegistryAuthError(503,'Approval workflow configuration unavailable')
        context=dict(base);flat={}
        for record in source_data or []:
            if isinstance(record,dict):flat.update(record)
        for field in policy.get('context_field_names') or []:
            if field in flat:context[field]=flat[field]
        field='submission_id' if kind=='intake' else 'change_request_id';key=str(value[field]);body={'policy_key':policy['policy_key'],'artifact_type':'registry.intake_form' if kind=='intake' else 'registry.change_request','artifact_id':key,'context':context,'requester':principal.subject or value.get('created_by')}
        for field_name,setting in [('callback_url','callback_url'),('callback_secret_id','callback_secret_id')]:
            setting_value=(self.workflow_settings.get(setting) or '').strip()
            if setting_value:body[field_name]=setting_value
        try:result=self.awe_client.call(token,'POST','/v1/awe/requests',body=body,extra_headers={'Idempotency-Key':('intake-' if kind=='intake' else 'cr-')+key})
        except RegistryError as error:
            if error.code=='AWE-007':self.fail('AWE_REQUEST_FAILED','AWE_REQUEST_FAILED: '+error.message)
            raise
        status=result.get('status');stage=result.get('current_stage_order');summary=(status+('-stage'+str(stage) if stage is not None else '')) if status else None;value={**value,'awe_request_id':result.get('request_id'),'awe_request_status_summary':summary};self.put_row(c,kind,value)
        return value
    def execute_policy_request(self,path,p,principal,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_policy_request(path,p,principal,pagination)
        if not isinstance(principal,RegistryPrincipal):raise ValueError('Trusted workflow principal required')
        with self.engine.begin() as c:
            if path==EXPORT_PATH:
                if self.definition(c,'register',p['register_id']) is None:self.fail('REGISTER_NOT_FOUND')
                selected=list(dict.fromkeys(key for key in p.get('selected_internal_record_ids') or [] if key));page=pagination or {};stamp=self.clock();key=str(uuid.uuid4());value={field:None for field in self.workflow_contract['export']['columns']};value.update(export_id=key,register_id=p['register_id'],requested_by=principal.subject,queued_at=stamp.isoformat(),export_format=p['export_format'],selection_mode='SELECTED' if selected else 'SEARCH_FILTER',selected_internal_record_ids=selected or None,search_text=None if selected else page.get('search_text') or None,filter_by=None if selected else page.get('filter_by') or None,sort_by=None if selected else page.get('sort_by') or None,policy_mnemonics=list(principal.policy_mnemonics),data_policies=list(principal.data_policies),batch_size=max(1,self.workflow_contract['export_batch_size']),last_processed_offset=0,export_status='PENDING',export_no_of_attempts=0)
                for field,column in self.workflow_contract['export']['columns'].items():
                    limit=column.get('max_length')
                    if limit is not None and value.get(field) is not None and len(str(value[field]))>limit:raise RegistryError('SYS-ERR-001')
                c.execute(insert(exports).values(id=key,owner=principal.subject,status='PENDING',queued_at=stamp,data=value));projection={field:value[field] for field in self.operation_contract['export']['selected_fields']};c.execute(insert(operations).values(**self.operation_values('export',projection)));self.record_decision(c,path,key,principal,stamp=stamp)
                return {'export_id':key,'status':'PENDING'},None
            value=self.intake_meta(c,p['submission_id'],lock=True);self.full_intake_scope(c,value,principal.data_policies);stamp=self.clock();value.update(draft_status='FINAL',finalized_at=stamp.isoformat(),last_updated_at=stamp.isoformat());self.put_row(c,'intake',value);sections=self.section_payloads(c,value,principal.data_policies);definition=self.require_definition(c,value['register_id']);form=self.definition(c,'form',value['form_id'])
            if form is None:self.fail('REQUEST_VALIDATION_ERROR',f"Intake form '{value['form_id']}' was not found")
            if form['register_id']!=value['register_id']:self.fail('REQUEST_VALIDATION_ERROR',f"Intake form '{value['form_id']}' does not belong to register '{value['register_id']}'")
            name=next((record['record_name'] for section in sections for record in section['records'] if record.get('record_name')),None);source=[record for section in sections for record in section['records']];value=self.start_workflow(c,'intake',value,principal,{'record_name':name,'intake_form_mnemonic':form['form_mnemonic'],'register_mnemonic':definition['register_mnemonic'],'submission_id':value['submission_id']},source);value=self.reconcile_summary(c,'intake',value);result=self.submission_payload(value,sections,name);self.record_decision(c,path,str(value['submission_id']),principal,stamp=stamp)
            return result,None
