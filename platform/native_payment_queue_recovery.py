"""Fenced payment queue reverse projection to Celery protocol 2.

Publication accepts an explicitly supplied broker; it never discovers or writes
to a production broker by itself. Public business rows must already be restored.
"""
import base64,datetime,hashlib,json,uuid
from psycopg2 import sql
from native_bridge_workers import NativeBridgeWorkers

class PaymentQueueRecovery:
    def __init__(self,recovery):self.recovery=recovery
    def plan(self):
        r=self.recovery
        if not r.admitted:raise ValueError('Fenced payment recovery admission required')
        # Compare entire public state, not only the status used to filter a job.
        for name,contract in r.settings['contract'].items():
            query=sql.SQL('SELECT to_jsonb(t)::text FROM public.{} t ORDER BY {}').format(sql.Identifier(name),sql.SQL(',').join(map(sql.Identifier,contract['keys'])))
            with r.source.cursor() as s,r.native.cursor() as n:
                s.execute(query);n.execute(query)
                if s.fetchall()!=n.fetchall():raise ValueError('Public state must be reconciled before queue export')
        with r.native.cursor() as n:
            n.execute('SELECT id,task,'+('identifier' if r.domain=='bridge' else 'args')+',available_at FROM kdbt_'+r.domain+"_queue.jobs WHERE state='PENDING' ORDER BY available_at,id")
            jobs=n.fetchall()
        output=[];skipped=0;seen=set()
        for identifier,task,target,available in jobs:
            args=[target] if r.domain=='bridge' else target
            if not isinstance(args,list) or len(args)!=1:raise ValueError('Explicit single-target payment task required')
            key=(task,str(args[0]))
            if key in seen:skipped+=1;continue
            seen.add(key)
            with r.source.cursor() as c:
                if r.domain=='bridge':
                    if task not in NativeBridgeWorkers.SPECS:raise ValueError('Unknown bridge queue task')
                    table,phase,column=NativeBridgeWorkers.SPECS[task];status=NativeBridgeWorkers.status_column(phase)
                    c.execute(sql.SQL('SELECT {} FROM public.{} WHERE {}=%s').format(sql.Identifier(status),sql.Identifier(table),sql.Identifier(column)),(args[0],));rows=c.fetchall()
                    if len(rows)>1:raise ValueError('Ambiguous bridge queue target')
                    terminal={'PROCESSED','ERROR','NOT_APPLICABLE','FUNDS_AVAILABLE' if phase=='funds_available' else 'FUNDS_BLOCK_SUCCESS' if phase=='funds_blocked' else 'PROCESSED'}
                    if not rows or rows[0][0] in terminal:skipped+=1;continue
                    if rows[0][0] not in {'PENDING','PROCESSING','PENDING_CHECK','CHECK_IN_PROGRESS','FUNDS_NOT_AVAILABLE','FUNDS_BLOCK_FAILURE'}:raise ValueError('Unknown bridge recovery status')
                    if task in {'check_funds_with_bank_worker','block_funds_with_bank_worker','disburse_funds_from_bank_worker'}:
                        if task=='disburse_funds_from_bank_worker':c.execute('SELECT disbursement_envelope_id FROM public.disbursement_batch_control WHERE id=%s',(args[0],));envelope=c.fetchone()[0]
                        else:envelope=args[0]
                        c.execute('SELECT cancellation_status FROM public.disbursement_envelopes WHERE id=%s',(envelope,))
                        if c.fetchone()[0]=='Cancelled':skipped+=1;continue
                else:
                    columns={'batching_request_worker':'batching_request_status','process_payments_worker':'payment_status','account_statement_generator':'account_statement_generation_status'}
                    if task not in columns:raise ValueError('Unknown bank queue task')
                    statement=task=='account_statement_generator';table='account_statements' if statement else 'initiate_payment_batch_requests';column='id' if statement else 'batch_id'
                    c.execute(sql.SQL('SELECT {} FROM public.{} WHERE {}=%s').format(sql.Identifier(columns[task]),sql.Identifier(table),sql.Identifier(column)),(args[0],));rows=c.fetchall()
                    if len(rows)>1:raise ValueError('Ambiguous bank queue target')
                    if not rows or rows[0][0] in {'SUCCESS','NOT_APPLICABLE'}:skipped+=1;continue
                    if rows[0][0] not in {'PENDING','PROCESSING','FAILED'}:raise ValueError('Unknown bank recovery status')
                    if task=='process_payments_worker':
                        c.execute('SELECT count(*) FROM public.accounting_logs l JOIN public.initiate_payment_requests p ON p.payment_reference_number=l.customer_reference_no WHERE p.batch_id=%s',(args[0],))
                        if c.fetchone()[0]:raise ValueError('Unfinished payment batch already has ledger effects; reconciliation required')
            output.append({'id':str(uuid.uuid5(uuid.NAMESPACE_URL,'kdbt-reverse:'+r.domain+':'+str(identifier))),'task':task,'args':args,'eta':available.isoformat()})
        return {'domain':r.domain,'jobs':output,'skipped':skipped,'native_pending':len(jobs)}

def celery_message(job,queue):
    if not queue or not isinstance(queue,str):raise ValueError('Explicit queue required')
    body=base64.b64encode(json.dumps([job['args'],{}, {'callbacks':None,'errbacks':None,'chain':None,'chord':None}],separators=(',',':')).encode()).decode()
    return json.dumps({'body':body,'content-encoding':'utf-8','content-type':'application/json','headers':{'lang':'py','task':job['task'],'id':job['id'],'root_id':job['id'],'parent_id':None,'eta':job['eta'],'expires':None,'retries':0,'timelimit':[None,None],'origin':'kdbt-fenced-recovery','ignore_result':False},'properties':{'correlation_id':job['id'],'delivery_mode':2,'delivery_info':{'exchange':'','routing_key':queue},'priority':0,'body_encoding':'base64','delivery_tag':job['id']}},sort_keys=True,separators=(',',':'))

def publish_plan(broker,plan,*,queue,generation):
    if type(generation) is not int or generation<1 or plan['domain'] not in {'bank','bridge'}:raise ValueError('Bounded recovery generation required')
    script="""local old=redis.call('GET',KEYS[2]); if old then if old~=ARGV[2] then return -1 else return 0 end end; redis.call('LPUSH',KEYS[1],ARGV[1]);redis.call('SET',KEYS[2],ARGV[2]);return 1"""
    count=0
    for job in plan['jobs']:
        message=celery_message(job,queue);digest=hashlib.sha256(message.encode()).hexdigest();receipt='kdbt:reverse:'+plan['domain']+':'+str(generation)+':'+job['id']
        result=broker.eval(script,2,queue,receipt,message,digest)
        if result==-1:raise ValueError('Queue publication receipt conflicts with recovered message')
        count+=result
    return count
