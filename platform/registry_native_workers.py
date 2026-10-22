"""Transactional native registry jobs; no Celery or legacy implementation imports.

Handlers run only for explicitly admitted pending jobs. A savepoint keeps
failed business writes out of the transaction that records the retry state.
"""
from copy import deepcopy
import json,uuid
from pathlib import Path
from sqlalchemy import select,update,text
from registry_approval_store import approval_jobs
from registry_row_store import rows
from registry_layout_store import layouts
from registry_record_store import records

TASKS=frozenset({'completion_score_worker','functional_id_allocation_worker','functional_id_updation_worker'})
EXCLUDED_COMPLETION_FIELDS=frozenset({'internal_record_id','link_internal_record_id','link_foundational_id',
    'functional_record_id','created_at','created_by','last_approved_at','last_approved_by','record_status'})

class WorkerFailure(ValueError):
    pass

def completion_score(values,columns,primary_keys,weight):
    eligible=set(columns)-set(primary_keys)-EXCLUDED_COMPLETION_FIELDS
    total=len(eligible)*len(values)
    filled=sum(value.get(field) is not None and not (isinstance(value.get(field),str) and not value[field].strip())
               for value in values for field in eligible)
    return (filled/total if total else 0.0)*(weight or 0.0)

def functional_affix(mnemonic):
    return {'individual':'IN-','household':'HH-'}.get((mnemonic or '').lower(),'DEFAULT-'),''

class NativeRegistryWorkers:
    def __init__(self,store,allocate_identifier=None,max_attempts=3):
        if not isinstance(max_attempts,int) or max_attempts<1:raise ValueError('Positive attempt limit required')
        self.store,self.allocate_identifier,self.max_attempts=store,allocate_identifier,max_attempts

    def run(self,task,key):
        if task not in TASKS:raise ValueError('Unimplemented worker task')
        kind='completion' if task=='completion_score_worker' else 'functional'
        prefix='compute' if kind=='completion' else 'id_allocation' if task=='functional_id_allocation_worker' else 'id_updation'
        status_field=prefix+'_status';attempt_field=prefix+('_number_of_attempts' if kind=='completion' else '_no_of_attempts')
        timestamp=prefix+('_processed_timestamp' if kind=='completion' else '_latest_timestamp')
        error_field=prefix+'_latest_error_code'
        with self.store.engine.begin() as c:
            value=c.execute(select(approval_jobs.c.data).where(approval_jobs.c.kind==kind,approval_jobs.c.id==key).with_for_update()).scalar_one_or_none()
            if value is None:return {'status':'NOT_FOUND'}
            value=deepcopy(value)
            if value.get(status_field)!='PENDING':return {'status':value.get(status_field),'skipped':True}
            if task=='functional_id_updation_worker' and value.get('id_allocation_status')!='COMPLETED':return {'status':'PENDING','skipped':True}
            if (value.get(attempt_field) or 0)>=self.max_attempts:
                value[status_field]='FAILED'
            else:
                try:
                    with c.begin_nested():
                        # Different queues for the same subject cannot overwrite
                        # each other's current record or completion score.
                        c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':'registry-worker:'+str(value.get('register_id'))+':'+str(value.get('internal_record_id'))})
                        if kind=='completion':self._completion(c,value)
                        elif task=='functional_id_allocation_worker':self._allocate(c,value)
                        else:self._acknowledge(value)
                    value[status_field]='COMPLETED';value[error_field]=None
                except Exception as error:
                    # Never persist arbitrary HTTP bodies, credentials or PII
                    # in the console's worker error field.
                    value[error_field]=str(error) if isinstance(error,WorkerFailure) else 'WORKER_EXECUTION_FAILED'
                    value[status_field]='FAILED' if (value.get(attempt_field) or 0)+1>=self.max_attempts else 'PENDING'
                value[attempt_field]=(value.get(attempt_field) or 0)+1
                value[timestamp]=self.store.clock().replace(tzinfo=None).isoformat()
            c.execute(update(approval_jobs).where(approval_jobs.c.kind==kind,approval_jobs.c.id==key).values(data=value))
            return {'status':value[status_field],'attempts':value.get(attempt_field,0),'error':value.get(error_field)}

    def _completion(self,c,job):
        section=c.execute(select(layouts.c.data).where(layouts.c.kind=='section',layouts.c.id==job['section_id'])).scalar_one_or_none()
        if section is None:raise WorkerFailure('COMPLETION_SECTION_NOT_FOUND')
        definition=self.store.require_definition(c,section['section_register_id'])
        interface=self.store.record_interface(definition)
        if not interface or not interface.get('current'):raise WorkerFailure('COMPLETION_RECORD_INTERFACE_NOT_FOUND')
        profile=interface['current']
        query=select(records.c.data).where(records.c.kind=='current',records.c.register_id==section['section_register_id'])
        query=query.where(records.c.link_id==job['internal_record_id']) if section['is_list'] else query.where(records.c.record_id==job['internal_record_id'])
        values=list(c.execute(query).scalars())
        if not section['is_list'] and not values:raise WorkerFailure('COMPLETION_RECORD_NOT_FOUND')
        score=completion_score(values,profile['columns'],profile['primary_key'],section.get('section_weightage'))
        matches=list(c.execute(select(rows.c.key,rows.c.data).where(rows.c.kind=='completion',rows.c.register_id==job['register_id'],rows.c.record_id==job['internal_record_id'],rows.c.section_id==job['section_id'])).all())
        if len(matches)>1:raise WorkerFailure('COMPLETION_RESULT_NOT_UNIQUE')
        profile=json.loads(Path(__file__).with_name('registry_row_contract.json').read_text())['completion']
        value=dict(matches[0].data) if matches else {field:None for field in profile['columns']}
        if not matches:value['id']=str(uuid.uuid4())
        value.update(register_id=job['register_id'],internal_record_id=job['internal_record_id'],section_id=job['section_id'],
            computed_section_completion_score=score,computed_timestamp=self.store.clock().replace(tzinfo=None).isoformat())
        self.store.put_row(c,'completion',value,new=not matches)

    def _allocate(self,c,job):
        definition=self.store.require_definition(c,job['register_id'])
        value=self.store.approval_record(c,definition,job['internal_record_id'])
        if value is None:raise WorkerFailure('FUNCTIONAL_RECORD_NOT_FOUND')
        if not callable(self.allocate_identifier):raise WorkerFailure('IDENTIFIER_SERVICE_NOT_CONFIGURED')
        resolved=self.allocate_identifier(definition['register_mnemonic'].lower())
        if not isinstance(resolved,str) or not resolved or not resolved.isdecimal():raise WorkerFailure('IDENTIFIER_RESPONSE_INVALID')
        prefix,suffix=functional_affix(definition['register_mnemonic'])
        updated={**value,'functional_record_id':prefix+resolved+suffix}
        updated=self.store.current_display(updated,definition['register_mnemonic'])
        self.store.save_register_snapshot(c,definition,'current',updated,new=False,existing=value)
        job.update(resolved_id=resolved,resolved_prefix=prefix,resolved_suffix=suffix,id_updation_status='PENDING')

    def _acknowledge(self,job):
        # The replaced worker's notification function is a local placeholder.
        # Preserve that exact behaviour; do not claim an external acknowledgement.
        if not ''.join(str(job.get(field) or '') for field in ['resolved_prefix','resolved_id','resolved_suffix']):
            raise WorkerFailure('RESOLVED_FUNCTIONAL_IDENTIFIER_MISSING')
