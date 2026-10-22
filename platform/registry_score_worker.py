"""Native configured score computation and atomic current/history persistence."""
import json,math,uuid
from pathlib import Path
from sqlalchemy import select,update,text
from registry_native_workers import WorkerFailure
from registry_score_config_store import scores
from registry_row_store import rows

TASKS=frozenset({'score_compute_worker'})
def poverty_score(attributes,values):
    total=0.0
    values=values if isinstance(values,dict) else {}
    for attribute in attributes:
        field=attribute['attribute_name']
        if field not in values:continue
        weight=float(attribute['attribute_weightage']);value=values[field]
        if not math.isfinite(weight):raise WorkerFailure('SCORE_WEIGHT_INVALID')
        if attribute.get('attribute_computation_required'):
            mapping=attribute.get('attribute_computation_value') or {}
            if not isinstance(mapping,dict):raise WorkerFailure('SCORE_LOOKUP_INVALID')
            value=mapping.get(str(value),0)
        if hasattr(value,'value'):value=value.value
        try:number=float(value) if value is not None else 0.0
        except (ValueError,TypeError):number=0.0
        if not math.isfinite(number):raise WorkerFailure('SCORE_VALUE_INVALID')
        total+=weight*number
    if not math.isfinite(total):raise WorkerFailure('SCORE_RESULT_INVALID')
    return round(total,4)

class NativeScoreWorker:
    def __init__(self,store,max_attempts=5,providers=None):
        if not isinstance(max_attempts,int) or max_attempts<1:raise ValueError('Positive attempt limit required')
        self.store,self.max_attempts=store,max_attempts
        self.providers={'POVERTY':poverty_score,**(providers or {})}
    def run(self,task,key):
        if task!='score_compute_worker':raise ValueError('Unimplemented score task')
        with self.store.engine.begin() as c:
            job=c.execute(select(scores.c.data).where(scores.c.kind=='queue',scores.c.id==key).with_for_update()).scalar_one_or_none()
            if job is None:return {'status':'NOT_FOUND'}
            job=dict(job)
            if job['compute_status']!='PENDING':return {'status':job['compute_status'],'skipped':True}
            if (job.get('compute_no_of_attempts') or 0)>=self.max_attempts:job['compute_status']='FAILED'
            else:
                try:
                    with c.begin_nested():self._compute(c,job)
                    job.update(compute_status='COMPLETED',compute_latest_error_code=None)
                except Exception as error:
                    job['compute_no_of_attempts']=(job.get('compute_no_of_attempts') or 0)+1
                    job['compute_status']='FAILED' if job['compute_no_of_attempts']>=self.max_attempts else 'PENDING'
                    job['compute_latest_error_code']=str(error) if isinstance(error,WorkerFailure) else 'SCORE_WORKER_FAILED'
                job['compute_latest_timestamp']=self.store.clock().replace(tzinfo=None).isoformat()
            self.store.put_score(c,'queue',job)
            return {'status':job['compute_status'],'attempts':job.get('compute_no_of_attempts',0),'error':job.get('compute_latest_error_code')}
    def _compute(self,c,job):
        definition=self.store.score(c,'definition',job['score_definition_id'])
        provider=self.providers.get(job['score_type'].upper())
        if not callable(provider):raise WorkerFailure('SCORE_PROVIDER_UNAVAILABLE')
        attributes=[value for value in self.store.score_rows(c,'attribute') if value['register_mnemonic']==definition['register_mnemonic'] and value['score_type']==definition['score_type']]
        result=float(provider(attributes,job.get('contributing_attribute_values')))
        if not math.isfinite(result):raise WorkerFailure('SCORE_RESULT_INVALID')
        c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':'registry-score:'+str(job.get('link_internal_record_id'))+':'+job['score_type']})
        existing=list(c.execute(select(rows.c.data).where(rows.c.kind=='score',rows.c.data['link_internal_record_id'].astext==job['link_internal_record_id'],rows.c.data['score_type'].astext==job['score_type'])).scalars())
        if len(existing)>1:raise WorkerFailure('SCORE_CURRENT_RESULT_NOT_UNIQUE')
        contract=json.loads(Path(__file__).with_name('registry_row_contract.json').read_text());stamp=self.store.clock().replace(tzinfo=None).isoformat()
        shared={'register_id':job['register_id'],'link_internal_record_id':job['link_internal_record_id'],'score_type':job['score_type'],'score_definition_id':job['score_definition_id'],
            'triggered_by_cr_id':job.get('change_request_id'),'triggered_by_submission_id':job.get('submission_id'),'computed_score':result,'computed_at':stamp}
        for kind in ['score','score-history']:
            value={field:None for field in contract[kind]['columns']}
            if kind=='score' and existing:value.update(existing[0])
            else:value['internal_record_id']=str(uuid.uuid4())
            value.update(shared)
            for field,column in contract[kind]['columns'].items():
                if not column['nullable'] and value[field] is None:raise WorkerFailure('SCORE_REQUIRED_RESULT_FIELD_MISSING')
            self.store.put_row(c,kind,value,new=kind!='score' or not existing)
