"""Transactional intake approval and durable import admission; no worker cutover."""
import uuid
from sqlalchemy import MetaData,Table,Column,String,DateTime,Index,select,insert,func,cast
from sqlalchemy.dialects.postgresql import JSONB
from registry_change_detail_store import RegistryChangeDetailStore
from registry_intake_record_store import intake_records
from registry_row_store import rows
from registry_document_store import documents
from registry_data_policy import RecordPolicyCompiler
from registry_metadata_api import RegistryPrincipal
from registry_metadata_store import RegistryError

metadata=MetaData()
imports=Table('console_registry_import_queue',metadata,Column('id',String,primary_key=True),Column('document_id',String,nullable=False),Column('status',String,nullable=False),Column('queued_at',DateTime,nullable=False),Column('actor',String,nullable=False),Column('policy_context',JSONB,nullable=False),Column('data',JSONB,nullable=False))
Index('ix_console_import_pending_time',imports.c.status,imports.c.queued_at)
Index('ix_console_import_document',imports.c.document_id)
Index('ux_console_import_document',imports.c.document_id,unique=True)
APPROVE_PATH='/intake-form-data/approve_intake_form_submission'
ENQUEUE_PATH='/input-mechanism-data/enqueue_import_file'
SUPPORTED_PATHS=frozenset([APPROVE_PATH,ENQUEUE_PATH])

class RegistryAdmissionStore(RegistryChangeDetailStore):
    def initialize(self):
        super().initialize();metadata.create_all(self.engine)
        for index in imports.indexes:index.create(self.engine,checkfirst=True)
    def full_intake_scope(self,c,value,policies):
        self.readable_submission(c,value['submission_id'],policies)
        for section,_ in self.submission_sections(c,value['form_id']):
            register=section['section_register_id'];meta=self.intake_interface(c,register);condition=RecordPolicyCompiler(intake_records,meta['columns']).resolve(policies,register)
            if condition is None:continue
            query=select(intake_records.c.key).where(intake_records.c.register_id==register,intake_records.c.submission_id==str(value['submission_id']),condition.is_not(True))
            if 'section_id' in meta['columns']:query=query.where(intake_records.c.section_id==section['section_id'])
            if c.execute(query.limit(1)).first():self.fail('RECORD_ACCESS_DENIED')
    def execute_policy_request(self,path,p,principal,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_policy_request(path,p,principal,pagination)
        if not isinstance(principal,RegistryPrincipal):raise ValueError('Trusted admission principal required')
        with self.engine.begin() as c:
            if path==ENQUEUE_PATH:
                self.find_documents(c,[p['document_id']]);stamp=self.clock();key=str(uuid.uuid4());contract=self.admission_contract['import'];value={field:None for field in contract['columns']}
                value.update(import_file_id=key,document_id=p['document_id'],data_model_id=p['data_model_id'],register_id=p['register_id'],intake_form_id=p['intake_form_id'],queued_by=principal.name or 'Unknown',queued_at=stamp.isoformat(),intake_form_ingestion_status='PENDING',intake_form_ingestion_attempts=0)
                for field,column in contract['columns'].items():
                    limit=column.get('max_length')
                    if limit is not None and value.get(field) is not None and len(str(value[field]))>limit:raise RegistryError('SYS-ERR-001')
                c.execute(insert(imports).values(id=key,document_id=value['document_id'],status='PENDING',queued_at=stamp,actor=principal.subject,policy_context=list(principal.data_policies),data=value));self.record_decision(c,path,key,principal,stamp=stamp)
                return {'import_file_id':key},None
            value=self.intake_meta(c,p['submission_id'],lock=True);self.full_intake_scope(c,value,principal.data_policies)
            if value['approval_status']!='PENDING':self.fail('REQUEST_VALIDATION_ERROR',f"Submission '{value['submission_id']}' is already in approval_status '{value['approval_status']}'")
            if value['number_of_verifications_required']>0:
                condition=(rows.c.kind=='verification')&(rows.c.data['submission_id'].astext==str(value['submission_id']));count=c.execute(select(func.count()).select_from(rows).where(condition)).scalar_one()
                # Retain validation of the first verification page as well as
                # the total; malformed stored verification data cannot approve.
                for verification in c.execute(select(rows.c.data).where(condition).order_by(cast(rows.c.data['verified_at'].astext,DateTime).desc()).limit(10)).scalars():self.models.model('VerificationData').model_validate(verification)
                if count<value['number_of_verifications_required']:self.fail('INTAKE_FORM_VERIFICATIONS_PENDING')
            stamp=self.clock();value.update(approval_status='APPROVED',approved_by=principal.name or 'Unknown',approved_at=stamp.isoformat(),last_updated_at=stamp.isoformat(),register_ingest_process_status='PENDING',register_ingest_process_last_error_code=None);self.put_row(c,'intake',value);value=self.reconcile_summary(c,'intake',value);sections=self.section_payloads(c,value,principal.data_policies);name=next((record['record_name'] for section in sections for record in section['records'] if record.get('record_name')),None);result=self.submission_payload(value,sections,name);self.record_decision(c,path,str(value['submission_id']),principal,stamp=stamp)
            return result,None
    @property
    def admission_contract(self):
        import json
        from pathlib import Path
        return json.loads(Path(__file__).with_name('registry_admission_contract.json').read_text())
