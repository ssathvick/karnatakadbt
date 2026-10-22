"""Transactional intake deletion and audited change-request rejection."""
from sqlalchemy import MetaData,Table,Column,String,Text,DateTime,BigInteger,Identity,Index,select,delete,insert
from registry_intake_view_store import RegistryIntakeViewStore
from registry_intake_record_store import intake_records
from registry_row_store import rows
from registry_document_store import documents
from registry_layout_store import layouts
from registry_metadata_api import RegistryPrincipal
from registry_data_policy import RecordPolicyCompiler,PolicyConfigurationError
from registry_record_store import record_timestamp
from registry_metadata_store import RegistryError

DELETE_PATH='/intake-form-data/delete_intake_form_submission'
SUPPORTED_PATHS=frozenset([DELETE_PATH,'/change-requests/reject_change_request','/change-requests-core-data/reject_change_request_for_core_data'])
metadata=MetaData()
decisions=Table('console_registry_decisions',metadata,Column('id',BigInteger,Identity(),primary_key=True),Column('path',String,nullable=False),Column('target_id',String,nullable=False),Column('actor',String,nullable=False),Column('actor_name',String),Column('reason',Text),Column('at',DateTime,nullable=False))
Index('ix_console_decision_target_time',decisions.c.target_id,decisions.c.at)

class RegistryDecisionStore(RegistryIntakeViewStore):
    def initialize(self):super().initialize();metadata.create_all(self.engine)
    def record_decision(self,c,path,target,principal,reason=None,stamp=None):
        c.execute(insert(decisions).values(path=path,target_id=target,actor=principal.subject,actor_name=principal.name,reason=reason,at=stamp or self.clock()))
    def reject_wire(self,value,core=False):
        fields=['record_name','register_id','tab_id','section_id','section_register_id','no_of_verifications_required','no_of_verifications_done','approval_status','change_request_id','internal_record_id','created_by','created_at','approved_by','approved_at']
        if not core:fields+=['awe_request_id','awe_request_status_summary']
        item={field:value.get(field) for field in fields}
        for field in ['created_at','approved_at']:item[field]=str(record_timestamp(value[field])) if value.get(field) else None
        return self.models.model('ChangeRequestResponsePayload').model_validate(item).model_dump(mode='json')
    def execute_policy_request(self,path,p,principal,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_policy_request(path,p,principal,pagination)
        if not isinstance(principal,RegistryPrincipal):raise ValueError('Trusted decision principal required')
        with self.engine.begin() as c:
            if path==DELETE_PATH:
                value=self.intake_meta(c,p['submission_id'],lock=True);self.readable_submission(c,value['submission_id'],principal.data_policies)
                result=self.submission_payload(value)
                for section,_ in self.submission_sections(c,value['form_id']):
                    register=section['section_register_id'];meta=self.intake_interface(c,register);conditions=[intake_records.c.register_id==register,intake_records.c.submission_id==str(value['submission_id'])]
                    if 'section_id' in meta['columns']:conditions.append(intake_records.c.section_id==section['section_id'])
                    policy=RecordPolicyCompiler(intake_records,meta['columns']).resolve(principal.data_policies,register)
                    if policy is not None and c.execute(select(intake_records.c.key).where(*conditions,policy.is_not(True)).limit(1)).first():self.fail('RECORD_ACCESS_DENIED')
                    c.execute(delete(intake_records).where(*conditions))
                c.execute(delete(documents).where(documents.c.kind=='intake',documents.c.data['submission_id'].as_string()==str(value['submission_id'])))
                c.execute(delete(rows).where(rows.c.kind=='intake',rows.c.key==self.row_key('intake',value)))
                self.record_decision(c,path,str(value['submission_id']),principal)
                return result,None
            core=path.startswith('/change-requests-core-data/');key=p.get('change_request_id')
            if core and not key:self.fail('INVALID_REQUEST','change_request_id is required for core-data change request operations')
            value=c.execute(select(rows.c.data).where(rows.c.kind=='change',rows.c.key==self.row_key('change',{'change_request_id':key})).with_for_update()).scalar_one_or_none()
            if value is None:self.fail('CHANGE_REQUEST_NOT_FOUND')
            value=dict(value)
            if value['approval_status']!='PENDING':self.fail('CHANGE_REQUEST_NOT_IN_PENDING_STATE')
            if core:
                if not value.get('section_id'):self.fail('INVALID_REQUEST','section_id is required for core-data change request operations')
                section=c.execute(select(layouts.c.data).where(layouts.c.kind=='section',layouts.c.id==value['section_id'])).scalar_one_or_none()
                if section is None:raise RegistryError('SECTION_NOT_FOUND','Section not found')
                if not section['is_core_section']:self.fail('NON_CORE_SECTION_OPERATION_NOT_ALLOWED')
            # Retain legacy state transitions, while applying authoritative
            # record restrictions whenever a policy scopes this register.
            if principal.data_policies:
                definition=self.require_definition(c,value['register_id']);interface=self.record_interface(definition)
                if not interface or not interface.get('current'):
                    if any(policy.get('register_id')==value['register_id'] for policy in principal.data_policies):raise PolicyConfigurationError()
                condition=self.record_policy(definition,principal.data_policies)
                if condition is not None:self.require_readable_subject(c,value['register_id'],value['internal_record_id'],principal.data_policies)
            stamp=self.clock();value.update(approval_status='REJECTED',approved_by='system' if core else principal.name or 'Unknown',approved_at=stamp.isoformat())
            self.put_row(c,'change',value);self.record_decision(c,path,key,principal,p.get('rejection_reason'),stamp)
            return self.reject_wire(value,core),None
