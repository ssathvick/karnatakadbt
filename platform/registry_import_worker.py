"""Resumable native file imports; admission and row receipt commit together."""
import csv,datetime,hashlib,io,json,uuid
from pathlib import Path
import openpyxl,xmltodict
from sqlalchemy import MetaData,Table,Column,String,Integer,DateTime,select,insert,update,func,text
from registry_admission_store import imports
from registry_document_store import documents
from registry_outgoing_workers import outputs,metadata as output_metadata
from registry_native_workers import WorkerFailure
from registry_metadata_api import RegistryPrincipal
from registry_worker_transaction import bound_store
from registry_import_history import history as preserved_receipts,metadata as preserved_metadata

metadata=MetaData()
receipts=Table('native_registry_import_records',metadata,Column('document_id',String,primary_key=True),Column('record_number',Integer,primary_key=True),
    Column('import_file_id',String,nullable=False),Column('correlation_id',String,nullable=False),Column('at',DateTime,nullable=False))
TASKS=frozenset({'import_file_process_worker'})
def flatten(value,prefix=''):
    if not isinstance(value,dict):raise WorkerFailure('IMPORT_RECORD_NOT_OBJECT')
    result={}
    for key,item in value.items():
        path=prefix+'.'+key if prefix else key
        if isinstance(item,dict):result.update(flatten(item,path))
        else:result[path]=item
    return result
def parse_import(content,filename):
    extension=Path(filename).suffix.lower()
    if extension in {'.csv','.tsv'}:return list(csv.DictReader(io.StringIO(content.decode('utf-8-sig')),delimiter=',' if extension=='.csv' else '\t'))
    if extension in {'.xls','.xlsx'}:
        workbook=openpyxl.load_workbook(io.BytesIO(content),read_only=True,data_only=True)
        try:
            iterator=workbook.active.iter_rows(values_only=True);first=next(iterator,None)
            if first is None:return []
            headers=[str(value).strip() if value is not None else 'column_'+str(i) for i,value in enumerate(first)]
            return [{header:str(row[i]).strip() if row[i] is not None else '' for i,header in enumerate(headers)} for row in iterator if any(value is not None for value in row)]
        finally:workbook.close()
    if extension=='.json':
        value=json.loads(content.decode())
        if isinstance(value,dict):value=next((item for item in value.values() if isinstance(item,list)),None)
        if not isinstance(value,list):raise WorkerFailure('IMPORT_JSON_ARRAY_REQUIRED')
        return [flatten(item) for item in value]
    if extension=='.jsonl':return [flatten(json.loads(line)) for line in content.decode().splitlines() if line.strip()]
    if extension=='.xml':
        if b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():raise WorkerFailure('IMPORT_XML_DTD_NOT_ALLOWED')
        value=xmltodict.parse(content.decode(),disable_entities=True)
        if len(value)==1:value=next(iter(value.values()))
        if not isinstance(value,dict):raise WorkerFailure('IMPORT_XML_RECORDS_REQUIRED')
        records=next((item for item in value.values() if isinstance(item,list)),None)
        return [flatten(item) for item in records] if records is not None else [flatten(value)]
    raise WorkerFailure('IMPORT_FORMAT_UNSUPPORTED')

class NativeImportWorker:
    def __init__(self,store,principal_provider,sender_id,signature,max_attempts=5):
        if not callable(principal_provider) or not sender_id or not signature:raise ValueError('Explicit import authority and sender settings required')
        if not isinstance(max_attempts,int) or max_attempts<1:raise ValueError('Positive attempt limit required')
        self.store,self.principal_provider,self.sender_id,self.signature,self.max_attempts=store,principal_provider,sender_id,signature,max_attempts
    def initialize(self):metadata.create_all(self.store.engine);output_metadata.create_all(self.store.engine);preserved_metadata.create_all(self.store.engine)
    def run(self,task,key):
        if task!='import_file_process_worker':raise ValueError('Unimplemented import task')
        # Session-level ownership spans the separately committed row receipts.
        # The finally clause releases it before returning a connection to pool.
        with self.store.engine.connect() as guard:
            locked=guard.execute(text('SELECT pg_try_advisory_lock(hashtextextended(:key,0))'),{'key':'registry-import:'+key}).scalar_one();guard.commit()
            if not locked:return {'status':'BUSY','skipped':True}
            try:return self._run(key)
            finally:
                guard.execute(text('SELECT pg_advisory_unlock(hashtextextended(:key,0))'),{'key':'registry-import:'+key});guard.commit()
    def _run(self,key):
        with self.store.engine.begin() as c:
            job=c.execute(select(imports.c.data).where(imports.c.id==key).with_for_update()).scalar_one_or_none()
            if job is None:return {'status':'NOT_FOUND'}
            job=dict(job)
            if job['intake_form_ingestion_status'] not in {'PENDING','PROCESSING'}:return {'status':job['intake_form_ingestion_status'],'skipped':True}
            if (job.get('intake_form_ingestion_attempts') or 0)>=self.max_attempts:
                job['intake_form_ingestion_status']='FAILED';self._save(c,key,job);return {'status':'FAILED'}
            job['intake_form_ingestion_attempts']=(job.get('intake_form_ingestion_attempts') or 0)+1;job['intake_form_ingestion_status']='PROCESSING';self._save(c,key,job)
        try:
            with self.store.engine.begin() as c:
                document=c.execute(select(documents.c.data).where(documents.c.kind=='catalog',documents.c.id==job['document_id'],documents.c.state=='READY')).scalar_one_or_none()
                model=self.store.definition(c,'model',job['data_model_id'])
                if not document or not model:raise WorkerFailure('IMPORT_INPUT_METADATA_MISSING')
                content=self.store.storage.get_bytes(document['document_store_id'],document['bucket']);digest=hashlib.sha256(content).hexdigest()
                known=c.execute(select(outputs.c.data).where(outputs.c.kind=='import-file-fingerprint',outputs.c.key==job['document_id'])).scalar_one_or_none()
                if known and known['sha256']!=digest:raise WorkerFailure('IMPORT_DOCUMENT_CHANGED')
                if not known:c.execute(insert(outputs).values(kind='import-file-fingerprint',key=job['document_id'],data={'sha256':digest}))
            values=parse_import(content,document['source_filename'])
            for number,value in enumerate(values,1):
                with self.store.engine.begin() as c:
                    job=dict(c.execute(select(imports.c.data).where(imports.c.id==key).with_for_update()).scalar_one())
                    if c.execute(select(receipts.c.record_number).where(receipts.c.document_id==job['document_id'],receipts.c.record_number==number)).first():continue
                    if c.execute(select(preserved_receipts.c.record_number).where(preserved_receipts.c.document_id==job['document_id'],preserved_receipts.c.record_number==number)).first():continue
                    principal=self.principal_provider(c,job)
                    if not isinstance(principal,RegistryPrincipal) or not principal.subject:raise WorkerFailure('IMPORT_AUTHORITY_UNAVAILABLE')
                    message=uuid.uuid5(uuid.NAMESPACE_URL,'kdbt-import:'+job['document_id']+':'+str(number)).hex
                    bound=bound_store(self.store,c)
                    response=bound.admit_ingest(value,{'message_id':message,'sender_id':self.sender_id,'signature':self.signature},
                        {'data_model':model['data_model_mnemonic'],'register_id':job.get('register_id'),'intake_form_id':job.get('intake_form_id')},principal)
                    stamp=self.store.clock().replace(tzinfo=None)
                    # Preserve the original worker's receipt contract in the
                    # SAME transaction as admission. Reverse handoff must not
                    # make an already admitted row look unprocessed to it.
                    source_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'kdbt-import-history:'+job['document_id']+':'+str(number)))
                    source_row={'import_file_record_id':source_id,'import_file_id':key,'document_id':job['document_id'],'record_number':number,'ingestion_timestamp':stamp.isoformat()}
                    c.execute(insert(preserved_receipts).values(id=source_id,document_id=job['document_id'],record_number=number,import_file_id=key,at=stamp,data=source_row))
                    c.execute(insert(receipts).values(document_id=job['document_id'],record_number=number,import_file_id=key,correlation_id=response['correlation_id'],at=stamp))
            with self.store.engine.begin() as c:
                job=dict(c.execute(select(imports.c.data).where(imports.c.id==key).with_for_update()).scalar_one())
                positions=select(receipts.c.record_number).where(receipts.c.document_id==job['document_id']).union(select(preserved_receipts.c.record_number).where(preserved_receipts.c.document_id==job['document_id'])).subquery()
                count=c.execute(select(func.count()).select_from(positions)).scalar_one()
                job.update(number_of_records_present=len(values),number_of_records_ingested=count,intake_form_ingestion_status='PROCESSED',intake_form_ingestion_error=None,intake_form_ingestion_timestamp=self.store.clock().replace(tzinfo=None).isoformat());self._save(c,key,job)
            return {'status':'PROCESSED','records':count}
        except Exception as error:
            with self.store.engine.begin() as c:
                job=dict(c.execute(select(imports.c.data).where(imports.c.id==key).with_for_update()).scalar_one())
                job.update(intake_form_ingestion_status='FAILED' if job['intake_form_ingestion_attempts']>=self.max_attempts else 'PENDING',
                    intake_form_ingestion_error=str(error) if isinstance(error,WorkerFailure) else 'IMPORT_WORKER_FAILED',intake_form_ingestion_timestamp=self.store.clock().replace(tzinfo=None).isoformat());self._save(c,key,job)
            return {'status':job['intake_form_ingestion_status'],'error':job['intake_form_ingestion_error']}
    def _save(self,c,key,value):c.execute(update(imports).where(imports.c.id==key).values(status=value['intake_form_ingestion_status'],data=value))
