"""Native transformed-message admission to drafts and change requests."""
import copy,datetime,uuid
from sqlalchemy import select,insert,update
from registry_worker_transaction import bound_store
from registry_native_workers import WorkerFailure
from registry_metadata_api import RegistryPrincipal
from registry_message_data_store import messages
from registry_outgoing_workers import outputs,metadata as output_metadata
from registry_row_store import rows
from registry_application_reference import application_reference

TASKS=frozenset({'ingest_data_worker','change_request_ingest_worker'})
def merge_sections(section,subject,incoming,accumulated,ids,new_id):
    incoming=copy.deepcopy(incoming);result=copy.deepcopy(accumulated)
    if not result:
        for row in incoming:row['internal_record_id']=row.get('internal_record_id') or str(new_id())
        return incoming
    index={row['internal_record_id']:i for i,row in enumerate(result)}
    def merge(target,row):result[target].update({field:value for field,value in row.items() if field!='edit_action' and value is not None})
    if section['section_register_id']==subject or not section['is_list']:
        if section['section_register_id']==subject and section['is_list'] or len(incoming)!=1:raise WorkerFailure('INGEST_SINGLE_SECTION_CARDINALITY')
        row=incoming[0];explicit=row.get('internal_record_id')
        if section['section_register_id']!=subject and explicit and explicit not in index:raise WorkerFailure('INGEST_SECTION_RECORD_UNKNOWN')
        target=0 if section['section_register_id']==subject else index.get(explicit,0);row['internal_record_id']=result[target]['internal_record_id'];merge(target,row);return result
    if not any(row.get('internal_record_id') for row in incoming) and len(incoming)<len(result):raise WorkerFailure('INGEST_LIST_MATCH_AMBIGUOUS')
    claimed=set()
    for position,row in enumerate(incoming):
        key=row.get('internal_record_id') or ids[position] if position<len(ids) else row.get('internal_record_id') or str(new_id())
        if key in claimed:raise WorkerFailure('INGEST_LIST_RECORD_DUPLICATE')
        if key not in index:index[key]=len(result);result.append({'internal_record_id':key})
        row['internal_record_id']=key;merge(index[key],row);claimed.add(key)
    return result

class NativePipelineWorkers:
    def __init__(self,store,principal_provider,max_attempts=5):
        if not callable(principal_provider):raise ValueError('Explicit worker authority required')
        if not isinstance(max_attempts,int) or max_attempts<1:raise ValueError('Positive attempt limit required')
        self.store,self.principal_provider,self.max_attempts=store,principal_provider,max_attempts
    def initialize(self):output_metadata.create_all(self.store.engine)
    def run(self,task,key):
        if task not in TASKS:raise ValueError('Unimplemented admission task')
        with self.store.engine.begin() as c:
            job=c.execute(select(messages.c.data).where(messages.c.kind=='classified',messages.c.key==key).with_for_update()).scalar_one_or_none()
            if job is None:return {'status':'NOT_FOUND'}
            job=copy.deepcopy(job)
            if job.get('ingestion_status')!='PENDING':return {'status':job.get('ingestion_status'),'skipped':True}
            if (job.get('ingestion_number_of_attempts') or 0)>=self.max_attempts:job['ingestion_status']='FAILED'
            else:
                intent=c.execute(select(outputs.c.data).where(outputs.c.kind=='ingest-intent',outputs.c.key==key)).scalar_one_or_none()
                if intent is None:
                    intent={'uuid':str(uuid.uuid5(uuid.NAMESPACE_URL,'kdbt-ingest:'+key)),'at':self.store.clock().isoformat(),
                        'reference':application_reference(self.store.intake_write_contract['application_reference_format'])}
                    c.execute(insert(outputs).values(kind='ingest-intent',key=key,data=intent))
                try:
                    attempt_job=copy.deepcopy(job)
                    with c.begin_nested():
                        if job.get('transformation_status')!='PROCESSED':raise WorkerFailure('INGEST_TRANSFORMATION_NOT_COMPLETE')
                        enriched=self.store.message(c,'enriched',key)
                        if not enriched:raise WorkerFailure('INGEST_TRANSFORMED_MESSAGE_MISSING')
                        principal=self.principal_provider(c,job)
                        if not isinstance(principal,RegistryPrincipal) or not principal.subject:raise WorkerFailure('INGEST_WORKER_AUTHORITY_UNAVAILABLE')
                        bound=bound_store(self.store,c);bound.clock=lambda:datetime.datetime.fromisoformat(intent['at'])
                        if task=='ingest_data_worker':self._intake(c,bound,attempt_job,enriched,principal,intent)
                        else:self._change(c,bound,attempt_job,enriched,principal,intent)
                    job=attempt_job
                    job.update(ingestion_status='PROCESSED',ingestion_latest_error_code=None)
                except Exception as error:
                    job['ingestion_status']='FAILED' if (job.get('ingestion_number_of_attempts') or 0)+1>=self.max_attempts else 'PENDING'
                    job['ingestion_latest_error_code']=str(error) if isinstance(error,WorkerFailure) else 'INGEST_ADMISSION_FAILED'
                job['ingestion_number_of_attempts']=(job.get('ingestion_number_of_attempts') or 0)+1;job['ingestion_date_time']=self.store.clock().replace(tzinfo=None).isoformat()
            c.execute(update(messages).where(messages.c.kind=='classified',messages.c.key==key).values(data=job))
            return {'status':job['ingestion_status'],'attempts':job.get('ingestion_number_of_attempts',0),'error':job.get('ingestion_latest_error_code')}
    def _intake(self,c,store,job,enriched,principal,intent):
        if (job.get('pipeline_action') or 'ADD')!='ADD':raise WorkerFailure('INGEST_ADD_ACTION_REQUIRED')
        sections=store.submission_sections(c,job.get('intake_form_id'));by_name={section['section_mnemonic']:section for section,_ in sections};transformed=enriched['transformed_data_json']
        if not sections or not isinstance(transformed,dict) or not transformed:raise WorkerFailure('INGEST_INTAKE_PAYLOAD_INVALID')
        if set(transformed)-set(by_name):raise WorkerFailure('INGEST_INTAKE_SECTION_UNKNOWN')
        primary=False
        for name,values in transformed.items():
            if not isinstance(values,list) or any(not isinstance(value,dict) for value in values):raise WorkerFailure('INGEST_INTAKE_RECORDS_INVALID')
            if by_name[name]['section_register_id']==job['register_id']:
                if by_name[name]['is_list'] or len(values)!=1:raise WorkerFailure('INGEST_SUBJECT_CARDINALITY_INVALID')
                primary=True
        if not primary:raise WorkerFailure('INGEST_SUBJECT_SECTION_MISSING')
        if job.get('intake_form_submission_id'):
            existing=c.execute(select(rows.c.data).where(rows.c.kind=='intake',rows.c.data['submission_id'].astext==str(job['intake_form_submission_id']))).scalar_one_or_none()
            if existing and existing['draft_status']!='DRAFT':raise WorkerFailure('INGEST_ALREADY_LINKED_TO_FINAL_SUBMISSION')
            if existing:store.execute_policy_request('/intake-form-data/delete_intake_form_submission',{'submission_id':existing['submission_id']},principal)
        count=[0]
        def new_id():
            count[0]+=1;return uuid.uuid5(uuid.UUID(intent['uuid']),'record:'+str(count[0]))
        store.uuid_factory=lambda:uuid.UUID(intent['uuid']);store.reference_factory=lambda:intent['reference']
        put=store.put_row
        def put_row(connection,kind,value,new=False):
            if kind=='intake':value.update(submission_source='PARTNER',partner_id=job.get('partner_id'))
            return put(connection,kind,value,new)
        store.put_row=put_row
        accumulated={};identifiers={};submission=None
        for section,_ in sections:
            values=transformed.get(section['section_mnemonic'])
            if values is None:continue
            register=section['section_register_id'];merged=merge_sections(section,job['register_id'],values,accumulated.get(register,[]),identifiers.get(register,[]),new_id)
            accumulated[register]=merged;identifiers[register]=[value['internal_record_id'] for value in merged]
            result,_=store.execute_policy_request('/intake-form-data/save_intake_form_submission',{'submission_id':submission,'register_id':job['register_id'],'form_id':job['intake_form_id'],'section_id':section['section_id'],'section_register_id':register,'section_payload':merged},principal)
            submission=result['submission_id']
        if not submission:raise WorkerFailure('INGEST_INTAKE_SUBMISSION_NOT_CREATED')
        store.execute_policy_request('/intake-form-data/finalize_intake_form_submission',{'submission_id':submission},principal);job['intake_form_submission_id']=submission
    def _change(self,c,store,job,enriched,principal,intent):
        if job.get('pipeline_action')!='UPDATE':raise WorkerFailure('INGEST_UPDATE_ACTION_REQUIRED')
        if not job.get('internal_record_id') or not job.get('section_id'):raise WorkerFailure('INGEST_CHANGE_TARGET_MISSING')
        section=next((value for value in store.rows(c,'section') if value['section_id']==job['section_id']),None)
        if section is None:raise WorkerFailure('INGEST_CHANGE_SECTION_MISSING')
        tabs={value['tab_id']:value for value in store.rows(c,'tab') if value['register_id']==job['register_id']}
        links=[value for value in store.rows(c,'link') if value['section_id']==job['section_id'] and value['register_id']==job['register_id'] and value['tab_id'] in tabs]
        links.sort(key=lambda value:(tabs[value['tab_id']]['tab_order'],value['section_order']))
        data=enriched['transformed_data_json'];values=data.get(section['section_mnemonic']) if isinstance(data,dict) else None
        if not links or not isinstance(values,list) or not values or not isinstance(values[0],dict):raise WorkerFailure('INGEST_CHANGE_PAYLOAD_INVALID')
        value={**values[0],'edit_action':'UPDATE','internal_record_id':job['internal_record_id']};stable=intent['uuid'];mapping={};put=store.put_row;decide=store.record_decision
        def put_row(connection,kind,value,new=False):
            if kind=='change':
                mapping[value['change_request_id']]=stable;value.update(change_request_id=stable,change_request_source='PARTNER',created_by='system',source_partner_id=job.get('partner_id'))
            elif kind=='change-payload' and value['change_request_id'] in mapping:value['change_request_id']=mapping[value['change_request_id']]
            return put(connection,kind,value,new)
        store.put_row=put_row
        store.record_decision=lambda connection,path,target,actor,**kwargs:decide(connection,path,mapping.get(target,target),actor,**kwargs)
        path='/change-requests-core-data/create_change_request_for_core_data' if section.get('is_core_section') else '/change-requests/create_change_request'
        store.execute_policy_request(path,{'register_id':job['register_id'],'tab_id':links[0]['tab_id'],'section_id':section['section_id'],'section_register_id':section['section_register_id'],'internal_record_id':job['internal_record_id'],'change_payload':[value]},principal)
        job['change_request_id']=stable
