"""Native policy-filtered hierarchy exports with durable queue completion."""
import base64,csv,datetime,decimal,json,os,re,tempfile,uuid,zipfile
from enum import Enum
from pathlib import Path
from openpyxl import Workbook
from sqlalchemy import select,update
from sqlalchemy.exc import DBAPIError
from registry_workflow_store import exports
from registry_operation_store import operations
from registry_record_store import records
from registry_data_policy import RecordPolicyCompiler
from registry_search_store import filter_conditions
from registry_native_workers import WorkerFailure

TASKS=frozenset({'register_export_worker'})
def safe_cell(value):
    if value is None:return ''
    if isinstance(value,Enum):value=value.value
    elif isinstance(value,(datetime.datetime,datetime.date,datetime.time)):value=value.isoformat()
    elif isinstance(value,(dict,list,tuple,set)):value=json.dumps(value,default=str,ensure_ascii=False)
    elif isinstance(value,bytes):value=base64.b64encode(value).decode('ascii')
    elif isinstance(value,(decimal.Decimal,uuid.UUID)):value=str(value)
    if isinstance(value,str):
        value=re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]','',value)
        if value.startswith(('=','+','-','@','\t','\r')):value="'"+value
    return value

class ExportFiles:
    def __init__(self,definitions,profiles,format,directory):
        if format not in {'XLSX','ZIP_CSV'}:raise WorkerFailure('EXPORT_FORMAT_UNSUPPORTED')
        self.format,self.directory=format,Path(directory);self.columns={key:list(profile['current']['columns']) for key,profile in profiles.items()}
        self.counts={key:0 for key in profiles};self.files={};self.sheets={};self.csv={};self.workbook=Workbook(write_only=True) if format=='XLSX' else None
        used=set()
        for definition in definitions:
            key=definition['register_id'];name=definition['register_mnemonic']
            if self.workbook:
                title=re.sub(r'[\[\]:*?/\\]','_',name).strip("'") or 'Register';title=title[:31];candidate=title;suffix=1
                while candidate.lower() in used:
                    tail='_'+str(suffix);candidate=title[:31-len(tail)]+tail;suffix+=1
                used.add(candidate.lower());sheet=self.workbook.create_sheet(candidate);sheet.append(self.columns[key]);self.sheets[key]=sheet
            else:
                name=re.sub(r'[^A-Za-z0-9._-]+','_',name+'-'+key).strip('._') or 'register';file=(self.directory/(name+'.csv')).open('w',newline='',encoding='utf-8');self.files[key]=file;self.csv[key]=csv.writer(file);self.csv[key].writerow(self.columns[key])
    def append(self,key,values):
        if self.workbook and self.counts[key]+len(values)>1048575:raise WorkerFailure('EXPORT_XLSX_ROW_LIMIT')
        for row in values:
            cells=[safe_cell(row.get(field)) for field in self.columns[key]]
            if self.workbook:self.sheets[key].append(cells)
            else:self.csv[key].writerow(cells)
        self.counts[key]+=len(values)
    def finish(self):
        if self.workbook:
            target=self.directory/'register-export.xlsx';self.workbook.save(target);return target,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        for file in self.files.values():file.close()
        target=self.directory/'register-export.zip'
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for file in self.files.values():archive.write(file.name,arcname=Path(file.name).name)
        return target,'application/zip'
    def close(self):
        for file in self.files.values():
            if not file.closed:file.close()

class NativeExportWorker:
    def __init__(self,store,max_attempts=3,url_expiry_hours=48):
        if not isinstance(max_attempts,int) or max_attempts<1 or url_expiry_hours<1:raise ValueError('Positive export limits required')
        self.store,self.max_attempts,self.url_expiry_hours=store,max_attempts,url_expiry_hours
    def run(self,task,key):
        if task!='register_export_worker':raise ValueError('Unimplemented export task')
        try:return self._run(key)
        except DBAPIError as error:
            if getattr(error.orig,'pgcode',None) not in {'40001','40P01'}:raise
            return {'status':'RETRY','skipped':True,'retryable':True}
    def _run(self,key):
        with self.store.engine.connect().execution_options(isolation_level='REPEATABLE READ') as c,c.begin():
            value=c.execute(select(exports.c.data).where(exports.c.id==key).with_for_update()).scalar_one_or_none()
            if value is None:return {'status':'NOT_FOUND'}
            value=dict(value)
            if value['export_status']!='PENDING':return {'status':value['export_status'],'skipped':True}
            if (value.get('export_no_of_attempts') or 0)>=self.max_attempts:value['export_status']='FAILED'
            else:
                value['export_no_of_attempts']=(value.get('export_no_of_attempts') or 0)+1
                try:
                    with c.begin_nested():self._export(c,value)
                    value['export_status']='COMPLETED';value['export_latest_error_code']=None
                except Exception as error:
                    value['export_status']='FAILED' if value['export_no_of_attempts']>=self.max_attempts else 'PENDING';value['last_processed_offset']=0
                    value['export_latest_error_code']=str(error) if isinstance(error,WorkerFailure) else 'EXPORT_WORKER_FAILED'
                value['export_latest_timestamp']=self.store.clock().replace(tzinfo=None).isoformat()
            c.execute(update(exports).where(exports.c.id==key).values(status=value['export_status'],data=value))
            projection={field:value[field] for field in self.store.operation_contract['export']['selected_fields']}
            c.execute(update(operations).where(operations.c.kind=='export',operations.c.data['export_id'].astext==key).values(data=projection))
            return {'status':value['export_status'],'attempts':value.get('export_no_of_attempts',0),'error':value.get('export_latest_error_code')}
    def _hierarchy(self,c,key):
        definitions={row['register_id']:row for row in self.store.definitions(c)}
        if key not in definitions:raise WorkerFailure('EXPORT_REGISTER_NOT_FOUND')
        main=definitions[key];ancestors=[];seen={key};parent=main.get('master_register_id')
        while parent:
            if parent in seen or parent not in definitions:raise WorkerFailure('EXPORT_PARENT_HIERARCHY_INVALID')
            seen.add(parent);ancestors.append(definitions[parent]);parent=definitions[parent].get('master_register_id')
        descendants=[];pending=[key];children={}
        while pending:
            parent=pending.pop(0);children[parent]=sorted([row for row in definitions.values() if row.get('master_register_id')==parent],key=lambda row:row['register_id'])
            for child in children[parent]:
                if child['register_id'] in seen:raise WorkerFailure('EXPORT_CHILD_HIERARCHY_INVALID')
                seen.add(child['register_id']);descendants.append(child);pending.append(child['register_id'])
        return list(reversed(ancestors)),main,descendants,children
    def _query(self,definition,policies,related=False):
        profile=self.store.record_interface(definition)
        if not profile or not profile.get('current'):raise WorkerFailure('EXPORT_RECORD_INTERFACE_MISSING')
        query=select(records.c.source_json).where(records.c.kind=='current',records.c.register_id==definition['register_id'])
        if related and 'record_status' in profile['current']['columns']:query=query.where(records.c.data['record_status'].astext=='ACTIVE')
        policy=self.store.record_policy(definition,policies)
        if policy is not None:query=query.where(policy)
        return query
    def _values(self,c,definition,query):
        columns=self.store.record_interface(definition)['current']['columns']
        return [self.store.record_value(raw,columns) for raw in c.execute(query).scalars()]
    def _export(self,c,job):
        if job.get('selection_mode') not in {'SELECTED','SEARCH_FILTER'}:raise WorkerFailure('EXPORT_SELECTION_MODE_INVALID')
        ancestors,main,descendants,children=self._hierarchy(c,job['register_id']);ordered=ancestors+[main]+descendants;policies=job.get('data_policies') or []
        profiles={definition['register_id']:self.store.hierarchy_interface(definition) for definition in ordered}
        columns=profiles[main['register_id']]['current']['columns'];query=self._query(main,policies)
        selected=job.get('selection_mode')=='SELECTED'
        if not selected:
            filters=job.get('filter_by');parsed=json.loads(filters) if isinstance(filters,str) else filters
            if 'record_status' in columns and (not isinstance(parsed,dict) or 'record_status' not in parsed):query=query.where(records.c.data['record_status'].astext=='ACTIVE')
            if (job.get('search_text') or '').strip():query=query.where(records.c.data['search_text'].astext.ilike('%'+job['search_text'].strip()+'%'))
            query=query.where(*filter_conditions((self.store.state(c,main['register_id']).get('schema') or {}).get('filter_schema'),columns,filters))
            field=(job.get('sort_by') or '').lstrip('-');descending=bool(job.get('sort_by') and job['sort_by'].startswith('-'))
            if field not in columns:field='last_approved_at';descending=True
            column,_=RecordPolicyCompiler(records,columns).column(field);query=query.order_by(column.desc() if descending else column.asc())
            if field!='internal_record_id':query=query.order_by(records.c.record_id.asc())
        batch=max(1,job.get('batch_size') or 2000);offset=0;seen={key:set() for key in profiles}
        with tempfile.TemporaryDirectory(prefix='kdbt-export-') as directory:
            writer=ExportFiles(ordered,profiles,job['export_format'],directory)
            try:
                while True:
                    if selected:
                        ids=(job.get('selected_internal_record_ids') or [])[offset:offset+batch]
                        if not ids:values=[]
                        else:
                            indexed={row['internal_record_id']:row for row in self._values(c,main,query.where(records.c.record_id.in_(ids)))};values=[indexed[key] for key in ids if key in indexed]
                        more=offset+batch<len(job.get('selected_internal_record_ids') or [])
                    else:values=self._values(c,main,query.offset(offset).limit(batch));more=len(values)==batch
                    grouped={key:[] for key in profiles};grouped[main['register_id']]=values;child_rows=values
                    for ancestor in reversed(ancestors):
                        ids={row.get('link_internal_record_id') for row in child_rows}-{None}
                        child_rows=self._values(c,ancestor,self._query(ancestor,policies,True).where(records.c.record_id.in_(ids)).order_by(records.c.record_id)) if ids else []
                        grouped[ancestor['register_id']]=child_rows
                    pending=[main]
                    while pending:
                        parent=pending.pop(0);ids=[row['internal_record_id'] for row in grouped[parent['register_id']]]
                        for child in children.get(parent['register_id'],[]):
                            grouped[child['register_id']]=self._values(c,child,self._query(child,policies,True).where(records.c.link_id.in_(ids)).order_by(records.c.record_id)) if ids else []
                            pending.append(child)
                    for definition in ordered:
                        key=definition['register_id'];unique=[]
                        for row in grouped[key]:
                            if row['internal_record_id'] not in seen[key]:seen[key].add(row['internal_record_id']);unique.append(row)
                        writer.append(key,unique)
                    offset+=batch
                    if not more:break
                target,content_type=writer.finish();object_id=job['export_id'];expiry=datetime.timedelta(hours=self.url_expiry_hours)
                with target.open('rb') as source:self.store.storage.put_object(object_id,source,target.stat().st_size,'export-files',content_type)
                job.update(last_processed_offset=offset,file_object_name=object_id,file_presigned_url=self.store.storage.get_url(object_id,'export-files',expires=expiry),
                    file_url_expires_at=(self.store.clock().replace(tzinfo=None)+expiry).isoformat(),total_records_exported=writer.counts[main['register_id']])
            finally:writer.close()
