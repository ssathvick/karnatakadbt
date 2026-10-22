"""Native pending-job selection and bounded periodic dispatch for all 18 tasks."""
import time
from sqlalchemy import select,func
from registry_approval_store import approval_jobs
from registry_row_store import rows
from registry_message_data_store import messages
from registry_score_config_store import scores
from registry_admission_store import imports
from registry_workflow_store import exports
from registry_dedup_workers import TASK_KINDS

TASKS=frozenset({'completion_score_worker','functional_id_allocation_worker','functional_id_updation_worker',
    'outgest_data_transformation_worker','outgest_data_publish_worker','outgest_topic_register_worker',
    'register_export_worker','score_compute_worker','import_file_process_worker','ingest_data_classification_worker',
    'ingest_data_transformation_worker','ingest_data_worker','change_request_ingest_worker',
    'intake_form_register_ingest_worker',*TASK_KINDS})

def intervals_from_settings(settings):
    result={}
    for task in TASKS:
        field=task.removesuffix('_worker')+'_beat_producer_frequency'
        if task in {'ingest_data_transformation_worker','outgest_data_transformation_worker'}:field='data_transformation_beat_producer_frequency'
        elif task in TASK_KINDS:field='deduplication_beat_producer_frequency'
        elif task=='change_request_ingest_worker':field='ingest_data_beat_producer_frequency'
        result[task]=settings.get(field) or settings.get('default_beat_producer_frequency',20)
    return result

class NativeRegistryDispatcher:
    def __init__(self,engine,handlers,intervals=None,batch_size=4,export_batch_size=5):
        if set(handlers)!=TASKS:raise ValueError('Every registry task must have exactly one native handler')
        if not 1<=batch_size<=1000 or not 1<=export_batch_size<=1000:raise ValueError('Invalid dispatch batch limit')
        self.engine,self.handlers=engine,handlers;self.batch_size,self.export_batch_size=batch_size,export_batch_size
        self.intervals={task:float((intervals or {}).get(task,20)) for task in TASKS}
        if any(not 1<=interval<=86400 for interval in self.intervals.values()):raise ValueError('Invalid dispatch interval')
        self.next_due={task:0 for task in TASKS}
    def pending_query(self,task,recover=False):
        if task not in TASKS:raise ValueError('Unknown registry task')
        states=['PENDING','PROCESSING'] if recover and task in {'import_file_process_worker','intake_form_register_ingest_worker'} else ['PENDING']
        if task in {'completion_score_worker','functional_id_allocation_worker','functional_id_updation_worker'}:
            kind='completion' if task=='completion_score_worker' else 'functional';field='compute_status' if kind=='completion' else 'id_allocation_status' if task=='functional_id_allocation_worker' else 'id_updation_status'
            query=select(approval_jobs.c.id).where(approval_jobs.c.kind==kind,approval_jobs.c.data[field].astext.in_(states)).order_by(approval_jobs.c.id)
            if task=='functional_id_updation_worker':query=query.where(approval_jobs.c.data['id_allocation_status'].astext=='COMPLETED')
        elif task in TASK_KINDS:
            kind=TASK_KINDS[task];intake=kind.startswith('intake');field={'change-register':'deduplication_register_status','change-change':'deduplication_change_request_status','intake-register':'deduplication_status_vs_register','intake-intake':'deduplication_status_vs_intake_forms'}[kind]
            query=select(rows.c.data['submission_id' if intake else 'change_request_id'].astext).where(rows.c.kind=='intake' if intake else rows.c.kind=='change',rows.c.data[field].astext.in_(states)).order_by(rows.c.sequence)
            if intake:query=query.where(rows.c.data['draft_status'].astext=='FINAL')
        elif task=='score_compute_worker':query=select(scores.c.id).where(scores.c.kind=='queue',scores.c.data['compute_status'].as_string().in_(states)).order_by(scores.c.position)
        elif task=='register_export_worker':query=select(exports.c.id).where(exports.c.status.in_(states)).order_by(exports.c.queued_at,exports.c.id)
        elif task=='import_file_process_worker':query=select(imports.c.id).where(imports.c.status.in_(states)).order_by(imports.c.queued_at,imports.c.id)
        elif task=='intake_form_register_ingest_worker':
            query=select(rows.c.data['submission_id'].astext).where(rows.c.kind=='intake',rows.c.data['register_ingest_process_status'].astext.in_(states),rows.c.data['approval_status'].astext=='APPROVED',rows.c.data['draft_status'].astext=='FINAL').order_by(rows.c.sequence)
        else:
            mapping={'outgest_data_transformation_worker':('outgoing','transformation_status'),'outgest_data_publish_worker':('outgoing','publish_status'),
                'outgest_topic_register_worker':('topic','websub_register_status'),'ingest_data_classification_worker':('incoming','classification_status'),
                'ingest_data_transformation_worker':('classified','transformation_status'),'ingest_data_worker':('classified','ingestion_status'),'change_request_ingest_worker':('classified','ingestion_status')}
            kind,field=mapping[task];query=select(messages.c.key).where(messages.c.kind==kind,messages.c.data[field].astext.in_(states)).order_by(messages.c.key)
            if task in {'ingest_data_worker','change_request_ingest_worker'}:
                action=func.coalesce(messages.c.data['pipeline_action'].astext,'ADD');query=query.where(action=='UPDATE' if task=='change_request_ingest_worker' else action!='UPDATE')
                query=query.where(messages.c.data['transformation_status'].astext=='PROCESSED')
            if task=='outgest_data_publish_worker':query=query.where(messages.c.data['transformation_status'].astext=='PROCESSED')
        return query.limit(self.export_batch_size if task=='register_export_worker' else self.batch_size)
    def pending(self,task,recover=False):
        with self.engine.connect() as c:return list(c.execute(self.pending_query(task,recover)).scalars())
    def tick(self,now=None):
        now=time.monotonic() if now is None else now;results=[]
        for task in sorted(TASKS):
            if now<self.next_due[task]:continue
            self.next_due[task]=now+self.intervals[task]
            for key in self.pending(task,recover=True):
                try:outcome=self.handlers[task].run(task,key);results.append({'task':task,'status':outcome.get('status')})
                except Exception:results.append({'task':task,'status':'RETRY','unexpected_failure':True})
        return results
