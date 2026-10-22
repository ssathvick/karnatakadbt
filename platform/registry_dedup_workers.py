"""Native duplicate detection over registry and intake projections."""
import datetime,json,math,uuid
from copy import deepcopy
from difflib import SequenceMatcher
from sqlalchemy import MetaData,Table,Column,String,Integer,select,insert,update,delete,or_
from registry_native_workers import WorkerFailure
from registry_record_store import records
from registry_intake_record_store import intake_records
from registry_row_store import rows
from registry_layout_store import layouts
from registry_dedup_result_store import matches
from registry_data_policy import RecordPolicyCompiler

metadata=MetaData()
runs=Table('native_registry_worker_runs',metadata,Column('task',String,primary_key=True),Column('key',String,primary_key=True),Column('attempts',Integer,nullable=False))
TASK_KINDS={'deduplication_register_worker':'change-register','deduplication_change_request_worker':'change-change',
    'deduplication_intake_forms_vs_register_worker':'intake-register','deduplication_intake_forms_vs_intake_forms_worker':'intake-intake'}
TASKS=frozenset(TASK_KINDS)
def normalized_payload(value):
    return value if isinstance(value,dict) else value[0] if isinstance(value,list) and value and isinstance(value[0],dict) else {}
def match_type(value):
    name=str(value or 'EXACT').strip().replace('-','_').upper()
    return {'NUMERIC':'NUMERIC_RANGE','DATE':'DATE_RANGE'}.get(name,name)
def similarity(left,right,mode):
    a,b=str(left).strip(),str(right).strip()
    if mode=='EXACT':return float(a.lower()==b.lower())
    if mode=='FUZZY':return SequenceMatcher(None,a.lower(),b.lower()).ratio()
    if mode=='PHONETIC':return 1.0 if a.lower()[:3]==b.lower()[:3] else .5
    if mode=='NUMERIC_RANGE':return float(a==b)
    if mode=='DATE_RANGE':return 1.0 if a==b else .8
    raise WorkerFailure('DEDUP_MATCH_TYPE_UNSUPPORTED')
def validated_schema(value):
    if not isinstance(value,list):raise WorkerFailure('DEDUP_SCHEMA_INVALID')
    result=[]
    for field in value:
        if not isinstance(field,dict) or not isinstance(field.get('field_name'),str) or not field['field_name']:raise WorkerFailure('DEDUP_SCHEMA_INVALID')
        mode=match_type(field.get('match_type'));weight=field.get('weight',1.0);threshold=field.get('similarity_threshold',.7)
        if mode not in {'EXACT','FUZZY','PHONETIC','NUMERIC_RANGE','DATE_RANGE'}:raise WorkerFailure('DEDUP_MATCH_TYPE_UNSUPPORTED')
        if not isinstance(weight,(float,int)) or not math.isfinite(weight) or weight<0:raise WorkerFailure('DEDUP_WEIGHT_INVALID')
        if not isinstance(threshold,(float,int)) or not math.isfinite(threshold) or not 0<=threshold<=1:raise WorkerFailure('DEDUP_SIMILARITY_THRESHOLD_INVALID')
        for key in ['range_value','range_days']:
            number=field.get(key,0)
            if not isinstance(number,(float,int)) or not math.isfinite(number) or number<0:raise WorkerFailure('DEDUP_RANGE_INVALID')
        result.append({**field,'match_type':mode,'weight':weight,'similarity_threshold':threshold})
    return result
def score_match(incoming,candidate,schema):
    total=sum(field['weight'] for field in schema);score=0;fields={}
    for field in schema:
        name=field['field_name'];left=incoming.get(name);right=candidate.get(name);mode=field['match_type']
        value=similarity(left,right,mode) if left and right else 0.0
        fields[name]={'incoming':str(left) if left and right else left,'candidate':str(right) if left and right else right,'similarity':value,'match_type':mode}
        if value>=field['similarity_threshold']:score+=value*field['weight']
    return (score/total*100 if total else 0.0),fields

class NativeDedupWorkers:
    def __init__(self,store,max_attempts=4):
        if not isinstance(max_attempts,int) or max_attempts<1:raise ValueError('Positive attempt limit required')
        self.store,self.max_attempts=store,max_attempts
    def initialize(self):metadata.create_all(self.store.engine)
    def run(self,task,key):
        if task not in TASKS:raise ValueError('Unimplemented duplicate detection task')
        kind=TASK_KINDS[task];intake=kind.startswith('intake');row_kind='intake' if intake else 'change';id_field='submission_id' if intake else 'change_request_id'
        status='deduplication_status_vs_'+('register' if kind=='intake-register' else 'intake_forms') if intake else 'deduplication_'+('register' if kind=='change-register' else 'change_request')+'_status'
        error='deduplication_'+('register_error' if kind=='intake-register' else 'intake_forms_error') if intake else status.removesuffix('_status')+'_failure_reason'
        with self.store.engine.begin() as c:
            original=c.execute(select(rows.c.data).where(rows.c.kind==row_kind,rows.c.data[id_field].astext==key).with_for_update()).scalar_one_or_none()
            if original is None:return {'status':'NOT_FOUND'}
            value=deepcopy(original)
            if value.get(status)!='PENDING':return {'status':value.get(status),'skipped':True}
            attempt=c.execute(select(runs.c.attempts).where(runs.c.task==task,runs.c.key==key)).scalar_one_or_none()
            attempts=attempt or 0
            if attempts>=self.max_attempts:value[status]='FAILED'
            else:
                try:
                    with c.begin_nested():
                        c.execute(delete(matches).where(matches.c.kind==kind,matches.c.target_id==key))
                        if intake:self._intake(c,kind,key,value)
                        else:self._change(c,kind,key,value)
                    value[status]='COMPLETED';value[error]=None
                except Exception as failure:
                    value[status]='FAILED' if attempts+1>=self.max_attempts else 'PENDING'
                    value[error]=str(failure) if isinstance(failure,WorkerFailure) else 'DEDUP_WORKER_FAILED'
                attempts+=1
            if intake:
                prefix='deduplication_register' if kind=='intake-register' else 'deduplication_intake_forms'
                count=prefix+('_forms_attempts' if kind=='intake-register' else '_attempts')
                if attempt is None or attempts>attempt:value[count]=(value.get(count) or 0)+1
                value[prefix+'_process_timestamp']=self.store.clock().replace(tzinfo=None).isoformat()
            self.store.put_row(c,row_kind,value)
            if attempt is None:c.execute(insert(runs).values(task=task,key=key,attempts=attempts))
            else:c.execute(update(runs).where(runs.c.task==task,runs.c.key==key).values(attempts=attempts))
            return {'status':value[status],'attempts':attempts,'error':value.get(error)}
    def _profile(self,c,register):
        definition=self.store.require_definition(c,register)
        if not definition.get('dedup_is_enabled'):return definition,[],None
        schema=validated_schema((self.store.state(c,register).get('schema') or {}).get('deduplicate_schema') or [])
        threshold=definition.get('dedup_threshold_score') or 0
        if not isinstance(threshold,(int,float)) or not math.isfinite(threshold) or not 0<=threshold<=100:raise WorkerFailure('DEDUP_RESULT_THRESHOLD_INVALID')
        return definition,schema,threshold
    def _register_candidates(self,c,definition,incoming,schema):
        profile=self.store.record_interface(definition)
        if not profile or not profile.get('current'):raise WorkerFailure('DEDUP_RECORD_INTERFACE_MISSING')
        profile=profile['current'];compiler=RecordPolicyCompiler(records,profile['columns']);conditions=[]
        for field in schema:
            name=field['field_name'];value=incoming.get(name);mode=field['match_type']
            if not value or name not in profile['columns']:continue
            column,_=compiler.column(name)
            if mode=='EXACT':conditions.append(column==value)
            elif mode=='FUZZY':conditions.append(column.ilike('%'+str(value)+'%'))
            elif mode=='PHONETIC':conditions.append(column.ilike(str(value).strip().lower()[:3]+'%'))
            elif mode=='NUMERIC_RANGE':
                try:number=float(value);conditions.append(column.between(number-field.get('range_value',0),number+field.get('range_value',0)))
                except (TypeError,ValueError):continue
            elif mode=='DATE_RANGE':
                try:
                    day=datetime.datetime.fromisoformat(value).date() if isinstance(value,str) else value
                    delta=datetime.timedelta(days=field.get('range_days',0));conditions.append(column.between(day-delta,day+delta))
                except (TypeError,ValueError):continue
        if not conditions:return []
        query=select(records.c.source_json).where(records.c.kind=='current',records.c.register_id==definition['register_id'],or_(*conditions))
        return [self.store.record_value(raw,profile['columns']) for raw in c.execute(query).scalars()]
    def _compute(self,c,register,incoming,candidates=None):
        incoming=normalized_payload(incoming)
        if not incoming:return []
        definition,schema,threshold=self._profile(c,register)
        if threshold is None:return []
        if candidates is None:candidates=[(value['internal_record_id'],value) for value in self._register_candidates(c,definition,incoming,schema)]
        results=[]
        for key,candidate in candidates:
            candidate=normalized_payload(candidate)
            if not candidate:continue
            score,fields=score_match(incoming,candidate,schema)
            if score>=threshold:results.append({'candidate_id':key,'score':score,'field_matches':fields})
        return results
    def _save(self,c,kind,key,result,section=None):
        value={'dedup_result_id':str(uuid.uuid4()),'match_score':result['score'],'field_matches':json.loads(json.dumps(result['field_matches'],default=str)),
            'created_at':self.store.clock().replace(tzinfo=None).isoformat()}
        value['submission_id' if kind.startswith('intake') else 'change_request_id']=key
        target={'change-register':'internal_record_id','change-change':'candidate_change_request_id','intake-register':'internal_record_id','intake-intake':'candidate_submission_id'}[kind]
        value[target]=result['candidate_id']
        if section:value['section_register_id']=section
        c.execute(insert(matches).values(kind=kind,id=value['dedup_result_id'],target_id=key,data=value))
    def _change_payload(self,c,key):
        value=c.execute(select(rows.c.data).where(rows.c.kind=='change-payload',rows.c.data['change_request_id'].astext==key)).scalar_one_or_none()
        if value is None:raise WorkerFailure('DEDUP_CHANGE_PAYLOAD_MISSING')
        return value['change_payload']
    def _change(self,c,kind,key,value):
        incoming=self._change_payload(c,key);candidates=None
        if kind=='change-change':
            others=list(c.execute(select(rows.c.data).where(rows.c.kind=='change',rows.c.register_id==value['register_id'],rows.c.data['change_request_id'].astext!=key,rows.c.data['deduplication_change_request_status'].astext=='PENDING')).scalars())
            candidates=[]
            for other in others:
                payload=c.execute(select(rows.c.data).where(rows.c.kind=='change-payload',rows.c.data['change_request_id'].astext==other['change_request_id'])).scalar_one_or_none()
                if payload:candidates.append((other['change_request_id'],payload['change_payload']))
        for result in self._compute(c,value['register_id'],incoming,candidates):self._save(c,kind,key,result)
    def _intake_rows(self,c,register,key):
        return [{field:value for field,value in row.items() if field!='submission_id'} for row in c.execute(select(intake_records.c.data).where(intake_records.c.register_id==register,intake_records.c.submission_id==key)).scalars()]
    def _intake(self,c,kind,key,value):
        sections=list(c.execute(select(layouts.c.data).where(layouts.c.kind=='section',layouts.c.data['register_id'].as_string()==value['register_id'])).scalars())
        others=list(c.execute(select(rows.c.data).where(rows.c.kind=='intake',rows.c.register_id==value['register_id'],rows.c.data['submission_id'].astext!=key,rows.c.data['approval_status'].astext!='APPROVED')).scalars()) if kind=='intake-intake' else []
        for section in sections:
            register=section['section_register_id'];definition=self.store.definition(c,'register',register)
            if not definition or definition['register_purpose']!='REGISTER' or register not in self.store.intake_contract:continue
            candidates=None if kind=='intake-register' else [(other['submission_id'],row) for other in others for row in self._intake_rows(c,register,other['submission_id'])]
            for incoming in self._intake_rows(c,register,key):
                results=self._compute(c,register,incoming,candidates)
                if kind=='intake-intake':
                    best={}
                    for result in results:
                        if result['candidate_id'] not in best or best[result['candidate_id']]['score']<result['score']:best[result['candidate_id']]=result
                    results=list(best.values())
                for result in results:self._save(c,kind,key,result,register)
