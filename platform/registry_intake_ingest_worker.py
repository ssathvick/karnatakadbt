"""Native approved-intake promotion, history, documents and downstream jobs."""
import copy,datetime,json,uuid
from sqlalchemy import select,insert,update,text
from registry_native_workers import WorkerFailure
from registry_row_store import rows
from registry_record_store import records
from registry_intake_record_store import intake_records
from registry_document_store import documents
from registry_message_data_store import messages
from registry_approval_domain import ApprovalDomainHooks,roster_counts
from registry_score_config_store import scores

TASKS=frozenset({'intake_form_register_ingest_worker'})
class NativeIntakeIngestWorker:
    def __init__(self,store,max_attempts=5):
        if not isinstance(max_attempts,int) or max_attempts<1:raise ValueError('Positive attempt limit required')
        self.store,self.max_attempts=store,max_attempts
    def run(self,task,key):
        if task!='intake_form_register_ingest_worker':raise ValueError('Unimplemented intake promotion task')
        with self.store.engine.connect() as guard:
            locked=guard.execute(text('SELECT pg_try_advisory_lock(hashtextextended(:key,0))'),{'key':'registry-intake-ingest:'+key}).scalar_one();guard.commit()
            if not locked:return {'status':'BUSY','skipped':True}
            try:return self._run(key)
            finally:
                guard.execute(text('SELECT pg_advisory_unlock(hashtextextended(:key,0))'),{'key':'registry-intake-ingest:'+key});guard.commit()
    def _read(self,c,key):return c.execute(select(rows.c.data).where(rows.c.kind=='intake',rows.c.data['submission_id'].astext==key).with_for_update()).scalar_one_or_none()
    def _save(self,c,value):self.store.put_row(c,'intake',value)
    def _run(self,key):
        with self.store.engine.begin() as c:
            value=self._read(c,key)
            if value is None:return {'status':'NOT_FOUND'}
            value=copy.deepcopy(value)
            if value['register_ingest_process_status'] not in {'PENDING','PROCESSING'}:return {'status':value['register_ingest_process_status'],'skipped':True}
            if value['draft_status']!='FINAL' or value['approval_status']!='APPROVED':
                value['register_ingest_process_last_error_code']='INTAKE_FINAL_APPROVAL_REQUIRED';self._save(c,value);return {'status':value['register_ingest_process_status'],'error':'INTAKE_FINAL_APPROVAL_REQUIRED'}
            if (value.get('register_ingest_process_attempts') or 0)>=self.max_attempts:
                value['register_ingest_process_status']='FAILED';self._save(c,value);return {'status':'FAILED'}
            value.update(register_ingest_process_status='PROCESSING',register_ingest_process_attempts=(value.get('register_ingest_process_attempts') or 0)+1,register_ingest_processed_timestamp=self.store.clock().replace(tzinfo=None).isoformat());self._save(c,value)
        try:
            with self.store.engine.begin() as c:
                value=self._read(c,key)
                if value is None:return {'status':'NOT_FOUND'}
                value=copy.deepcopy(value)
                if value['draft_status']!='FINAL' or value['approval_status']!='APPROVED':raise WorkerFailure('INTAKE_FINAL_APPROVAL_REQUIRED')
                self._promote(c,value)
                value.update(register_ingest_process_status='PROCESSED',register_ingest_process_last_error_code=None,register_ingest_processed_timestamp=self.store.clock().replace(tzinfo=None).isoformat());self._save(c,value)
            return {'status':'PROCESSED','attempts':value['register_ingest_process_attempts']}
        except Exception as error:
            with self.store.engine.begin() as c:
                value=self._read(c,key)
                if value is None:return {'status':'NOT_FOUND'}
                value=copy.deepcopy(value);value.update(register_ingest_process_status='FAILED' if value['register_ingest_process_attempts']>=self.max_attempts else 'PENDING',
                    register_ingest_process_last_error_code=str(error) if isinstance(error,WorkerFailure) else 'INTAKE_PROMOTION_FAILED',register_ingest_processed_timestamp=self.store.clock().replace(tzinfo=None).isoformat());self._save(c,value)
            return {'status':value['register_ingest_process_status'],'error':value['register_ingest_process_last_error_code']}
    def _mapping(self,c,section,subject):
        sections={value['section_id']:value for value in self.store.rows(c,'section')};links=[value for value in self.store.rows(c,'link') if value['register_id']==subject]
        exact=[link for link in links if link['section_id']==section['section_id']]
        if len(exact)>1:raise WorkerFailure('INTAKE_HISTORY_EXACT_MAPPING_AMBIGUOUS')
        if exact:return section,exact[0]['tab_id']
        candidates=[(sections[link['section_id']],link['tab_id']) for link in sorted(links,key=lambda value:value['section_order']) if link['section_id'] in sections and sections[link['section_id']]['section_register_id']==section['section_register_id']]
        if len(candidates)==1:return candidates[0]
        same=[pair for pair in candidates if pair[0]['section_mnemonic']==section['section_mnemonic']]
        if len(same)==1:return same[0]
        lists=[pair for pair in candidates if pair[0]['is_list']]
        return lists[0] if section['is_list'] and len(lists)==1 else None
    def _promote(self,c,submission):
        sections=[section for section,_ in self.store.submission_sections(c,submission['form_id'])];unique={};intakes={};definitions={}
        for section in sections:unique.setdefault(section['section_register_id'],section)
        for register in unique:
            definition=self.store.require_definition(c,register);definitions[register]=definition
            profile=self.store.intake_contract.get(register)
            if not profile:raise WorkerFailure('INTAKE_DOMAIN_INTERFACE_MISSING')
            intakes[register]=[self.store.record_value(raw,profile['columns']) for raw in c.execute(select(intake_records.c.source_json).where(intake_records.c.register_id==register,intake_records.c.submission_id==submission['submission_id']).order_by(intake_records.c.position)).scalars()]
        subject_rows=intakes.get(submission['register_id'],[]);subject=subject_rows[0]['internal_record_id'] if subject_rows else None
        inserted={}
        # Lock shared household rows in a stable order before roster updates.
        household=next((value for value in self.store.definitions(c) if value['register_mnemonic']=='Household'),None)
        links={row.get('link_internal_record_id') for register,values in intakes.items() if definitions[register]['register_mnemonic']=='Individual' for row in values}-{None}
        if household and links:list(c.execute(select(records.c.key).where(records.c.kind=='current',records.c.register_id==household['register_id'],records.c.record_id.in_(links)).order_by(records.c.record_id).with_for_update()))
        for register,section in unique.items():
            definition=definitions[register];profile=self.store.approval_contract['models']['G2PRegister'+definition['register_mnemonic']]
            inserted[register]=[]
            for intake in intakes[register]:
                if self.store.approval_record(c,definition,intake['internal_record_id'],lock=False) is not None:raise WorkerFailure('INTAKE_REGISTER_RECORD_ALREADY_EXISTS')
                value=self.store.approval_defaults(profile)
                for field,item in intake.items():
                    if field in value and (item is not None or value[field] is None):value[field]=item
                for field,item in [('created_by',submission['created_by']),('created_at',submission['first_created_at']),('last_approved_by',submission.get('approved_by') or 'system'),('last_approved_at',submission.get('approved_at') or self.store.clock().isoformat())]:
                    if field in value:value[field]=item
                if definition['register_purpose']=='REGISTER' and definition.get('functional_id_generation_required') and not value.get('functional_record_id'):
                    self.store.native_job(c,'functional','G2PFunctionalIdGenerationQueue',{'register_id':register,'internal_record_id':value['internal_record_id']});value['functional_record_id']='TEMP-'+uuid.uuid4().hex
                value=self.store.current_display(value,definition['register_mnemonic'])
                self._nonnull(profile,value);self.store.save_register_snapshot(c,definition,'current',value,new=True)
                inserted[register].append(value['internal_record_id'])
                self._documents(c,submission,sections,register,value['internal_record_id'])
                if definition['register_mnemonic']=='Individual' and value.get('link_internal_record_id') and household:
                    hooks=ApprovalDomainHooks(register,household['register_id']);member=hooks.member(c,value['internal_record_id']);locked=hooks.lock_households(c,member,[])
                    members=list(c.execute(select(records.c.data).where(records.c.kind=='current',records.c.register_id==register,records.c.link_id==value['link_internal_record_id'])).scalars())
                    if value['link_internal_record_id'] in locked:
                        hooks.apply(c,{value['link_internal_record_id']:roster_counts(members)})
                        refreshed=self.store.approval_record(c,household,value['link_internal_record_id'],lock=False)
                        self.store.save_register_snapshot(c,household,'current',self.store.current_display(copy.deepcopy(refreshed),household['register_mnemonic']),new=False,existing=refreshed)
        for section in sections:
            register=section['section_register_id'];mapping=self._mapping(c,section,submission['register_id'])
            if mapping is None:continue
            mapped,tab=mapping;definition=definitions[register];profile=self.store.approval_contract['models']['G2PRegisterHistory'+definition['register_mnemonic']]
            for key in inserted[register]:
                current=self.store.approval_record(c,definition,key,lock=False);history=self.store.approval_defaults(profile)
                for field,item in current.items():
                    if field in history:history[field]=item
                history.update(history_record_id=str(uuid.uuid4()),internal_record_id=key,tab_id=tab,section_id=mapped['section_id'],change_request_id=None,submission_id=submission['submission_id'],change_request_source='INTAKE_FORM',is_primary_section=register==submission['register_id'],
                    created_by=submission['created_by'],created_at=submission['first_created_at'],approved_by=submission.get('approved_by') or 'system',approved_at=submission.get('approved_at') or self.store.clock().isoformat())
                if 'subject_internal_record_id' in history:history['subject_internal_record_id']=subject or (key if register==submission['register_id'] else None)
                self._nonnull(profile,history);self.store.save_register_snapshot(c,definition,'history',history,new=True)
        for register,keys in inserted.items():
            definition=definitions[register]
            for key in keys:
                self._outgoing(c,submission,definition,key)
                if definition['register_purpose']!='REGISTER':continue
                if definition.get('completion_score_required'):
                    for section in self.store.rows(c,'section'):
                        if section['register_id']==register and (section['section_register_id']==register or section['is_list']):self.store.native_job(c,'completion','G2PCompletionScoreComputationQueue',{'register_id':register,'internal_record_id':key,'section_id':section['section_id'],'submission_id':submission['submission_id']})
                section=unique[register];payload=[{**intake,'edit_action':'ADD'} for intake in intakes[register] if intake['internal_record_id']==key]
                self.store.approval_score_jobs(c,{'register_id':register,'section_register_id':register,'internal_record_id':key,'change_request_id':'','submission_id':submission['submission_id']},section,payload,score_only=True)
                pending=list(c.execute(select(scores.c.id,scores.c.data).where(scores.c.kind=='queue',scores.c.data['link_internal_record_id'].as_string()==key,scores.c.data['compute_status'].as_string()=='PENDING')).all())
                for queued in pending:c.execute(update(scores).where(scores.c.kind=='queue',scores.c.id==queued.id).values(data={**queued.data,'submission_id':submission['submission_id'],'change_request_id':''}))
    def _nonnull(self,profile,value):
        if any(not meta['nullable'] and value.get(field) is None for field,meta in profile['columns'].items()):raise WorkerFailure('INTAKE_REQUIRED_REGISTER_FIELD_MISSING')
    def _documents(self,c,submission,sections,register,key):
        by_id={section['section_id']:section for section in sections}
        links=list(c.execute(select(documents.c.data).where(documents.c.kind=='intake',documents.c.data['submission_id'].as_string()==submission['submission_id'])).scalars())
        for link in links:
            section=by_id.get(link['section_id'])
            if not section or section['section_register_id']!=register:continue
            mapping=self._mapping(c,section,submission['register_id']);section_id=mapping[0]['section_id'] if mapping else section['section_id']
            history=self.store.approval_defaults(self.store.approval_contract['queues']['G2PRegisterDocumentHistory']);history.update(internal_record_id=key,change_request_id=None,submission_id=submission['submission_id'],change_request_source='INTAKE_FORM',section_id=section_id,document_id=link['document_id'],label=link.get('label'),
                created_by=submission['created_by'],created_at=submission['first_created_at'],approved_by=submission.get('approved_by') or 'system',approved_at=submission.get('approved_at') or submission['last_updated_at'])
            self.store.put_doc(c,'history',str(uuid.uuid4()),history)
            existing=c.execute(select(documents.c.id,documents.c.data).where(documents.c.kind=='section',documents.c.data['internal_record_id'].as_string()==key,documents.c.data['document_id'].as_string()==link['document_id'])).first()
            if existing:c.execute(update(documents).where(documents.c.kind=='section',documents.c.id==existing.id).values(data={**existing.data,'section_id':section_id,'label':link.get('label')}))
            else:self.store.put_doc(c,'section',str(uuid.uuid4()),{**self.store.approval_defaults(self.store.approval_contract['queues']['G2PRegisterSectionDocument']),'internal_record_id':key,'document_id':link['document_id'],'section_id':section_id,'label':link.get('label')})
    def _outgoing(self,c,submission,definition,key):
        if not definition.get('outgest_applicable'):return
        topics=[value for value in self.store.message_rows(c,'topic') if value['register_id']==definition['register_id'] and value['is_active']]
        if not topics:return
        record=self.store.approval_outgoing_hierarchy(c,definition,key);payload_id=':'.join([submission['submission_id'],definition['register_id'],key])
        value={**self.store.approval_defaults(self.store.approval_contract['queues']['OutgoingRawDataPayload']),'payload_id':payload_id,'change_request_id':None,'intake_form_submission_id':submission['submission_id'],'raw_data_json':record,'raw_data_text':json.dumps(record,default=str)}
        c.execute(insert(messages).values(kind='outgoing-payload',key=payload_id,data=value))
        partner=submission.get('partner_id')
        if partner:
            if self.store.partner_client is None:raise WorkerFailure('INTAKE_PARTNER_AUTHORITY_UNAVAILABLE')
            partner=self.store.partner_client.require_active(partner)['partner_id']
        for topic in topics:
            value={**self.store.approval_defaults(self.store.approval_contract['queues']['OutgoingRawData']),'outgest_id':str(uuid.uuid4()),'payload_id':payload_id,'change_request_id':None,'intake_form_submission_id':submission['submission_id'],'internal_record_id':key,'register_id':definition['register_id'],'data_model_id':topic['data_model_id'],'topic_id':topic['topic_id'],
                'changed_by':submission.get('approved_by') or 'system','changed_at':submission.get('approved_at') or self.store.clock().isoformat(),'approved_by':submission.get('approved_by'),'approved_at':submission.get('approved_at'),'changed_by_partner_id':partner,'transformation_status':'PENDING'}
            c.execute(insert(messages).values(kind='outgoing',key=value['outgest_id'],data=value))
