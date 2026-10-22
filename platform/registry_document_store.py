"""Custom document catalog, associations, upload journal and deletion outbox."""
import datetime,hashlib,io,json,uuid
from sqlalchemy import MetaData,Table,Column,String,JSON,Integer,Index,select,insert,update,delete,func
from registry_score_config_store import RegistryScoreConfigStore
from registry_metadata_store import RegistryError
from registry_document_validation import validate_document

metadata=MetaData()
documents=Table('console_document_catalog',metadata,Column('kind',String,primary_key=True),Column('id',String,primary_key=True),Column('data',JSON,nullable=False),Column('state',String,nullable=False),Column('position',Integer,nullable=False))
Index('ix_console_document_state',documents.c.kind,documents.c.state,documents.c.position)
for field in ['document_id','change_request_id','submission_id','internal_record_id']:
    Index('ix_console_document_'+field,documents.c.kind,documents.c.data[field].as_string())
Index('ix_console_unique_document_object',documents.c.data['document_store_id'].as_string(),unique=True,postgresql_where=documents.c.kind=='catalog')
SUPPORTED_PATHS=frozenset('/documents/'+name for name in ['upload_documents','delete_documents','get_documents','get_change_request_documents','get_intake_form_documents','get_section_documents'])

class RegistryDocumentStore(RegistryScoreConfigStore):
    def __init__(self,engine,storage=None):super().__init__(engine);self.storage=storage
    def initialize(self):
        super().initialize();metadata.create_all(self.engine)
        for index in documents.indexes:index.create(self.engine,checkfirst=True)
    def doc_rows(self,c,kind,state='READY'):
        query=select(documents.c.data).where(documents.c.kind==kind)
        if state is not None:query=query.where(documents.c.state==state)
        return [dict(row) for row in c.execute(query.order_by(documents.c.position)).scalars()]
    def put_doc(self,c,kind,key,row,state='READY'):
        position=(c.execute(select(func.max(documents.c.position))).scalar_one() or 0)+1
        c.execute(insert(documents).values(kind=kind,id=key,data=row,state=state,position=position))
    def seed_documents(self,dataset):
        with self.write() as c:
            if c.execute(select(documents.c.id)).first():raise RuntimeError('Refusing to overwrite documents')
            for kind,rows in dataset.items():
                for row in rows:
                    key=row['document_id'] if kind=='catalog' else hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()
                    self.put_doc(c,kind,key,row)
    def doc_wire(self,row,section=None,label=None):
        if self.storage is None:raise RuntimeError('Document storage is not configured')
        result={**row,'presigned_url':self.storage.get_url(row['document_store_id'],row['bucket']),'section_id':section,'label':label}
        return self.models.model('DocumentData').model_validate(result).model_dump(mode='json')
    def find_documents(self,c,ids):
        wanted=set(ids);rows=list(c.execute(select(documents.c.data).where(documents.c.kind=='catalog',documents.c.state=='READY',documents.c.id.in_(wanted)).order_by(documents.c.position)).scalars())
        found={row['document_id'] for row in rows};missing=[key for key in ids if key not in found]
        if missing:self.fail('DOCUMENT_NOT_FOUND',f'DOCUMENT_NOT_FOUND: {missing}')
        return rows
    def flush_document_deletions(self):
        if self.storage is None:return 0
        with self.engine.connect() as c:jobs=list(c.execute(select(documents.c.id,documents.c.data).where(documents.c.kind=='deletion')).all())
        done=0
        for key,row in jobs:
            try:self.storage.delete(row['document_store_id'],row['bucket'])
            except Exception:continue
            with self.engine.begin() as c:c.execute(delete(documents).where(documents.c.kind=='deletion',documents.c.id==key))
            done+=1
        return done
    def cancel_pending_uploads(self,ids,older_than=None):
        with self.write() as c:
            query=select(documents.c.data).where(documents.c.kind=='catalog',documents.c.state=='PENDING')
            if ids is not None:query=query.where(documents.c.id.in_(ids))
            rows=list(c.execute(query).scalars())
            for row in rows:
                if ids is not None and row['document_id'] not in ids:continue
                created=datetime.datetime.fromisoformat(row['created_at'])
                if older_than is not None and created>=older_than:continue
                self.put_doc(c,'deletion',str(uuid.uuid4()),{'document_store_id':row['document_store_id'],'bucket':row['bucket']})
                c.execute(delete(documents).where(documents.c.kind=='catalog',documents.c.id==row['document_id'],documents.c.state=='PENDING'))
    def upload(self,files,bucket,principal):
        if self.storage is None:raise RuntimeError('Document storage is not configured')
        prepared=[]
        for filename,data,content_type in files:
            mime=validate_document(data,filename,bucket,content_type)
            row={'document_id':str(uuid.uuid4()),'document_store_id':str(uuid.uuid4()),'bucket':bucket,'source_filename':filename,'created_by':principal.name or 'Unknown','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
            self.models.model('DocumentData').model_validate(row)
            prepared.append((row,data,mime))
        # Persist admission before object writes. A process/database failure can
        # leave PENDING work, but can never expose a half-uploaded document.
        with self.write() as c:
            for row,_,_ in prepared:self.put_doc(c,'catalog',row['document_id'],row,state='PENDING')
        ids={row['document_id'] for row,_,_ in prepared}
        try:
            for row,data,mime in prepared:self.storage.put_object(row['document_store_id'],io.BytesIO(data),len(data),bucket,mime)
            with self.write() as c:
                c.execute(update(documents).where(documents.c.kind=='catalog',documents.c.id.in_(ids),documents.c.state=='PENDING').values(state='READY'))
                self.record(c,principal.subject,'upload_documents','batch',{'document_ids':sorted(ids)})
        except Exception:
            # Reconcile using durable DB state: never delete an object when an
            # ambiguous commit may already have made its catalog entry READY.
            try:self.cancel_pending_uploads(ids);self.flush_document_deletions()
            except Exception:pass
            raise
        return {'documents':[self.doc_wire(row) for row,_,_ in prepared]}
    def execute_request(self,path,p,actor,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_request(path,p,actor,pagination)
        operation=path.rsplit('/',1)[-1]
        if operation=='upload_documents':raise RuntimeError('Multipart upload endpoint is required')
        if operation=='delete_documents':
            ids=p['document_ids'];wanted=set(ids)
            with self.write() as c:
                rows=self.find_documents(c,ids)
                for row in rows:self.put_doc(c,'deletion',str(uuid.uuid4()),{'document_store_id':row['document_store_id'],'bucket':row['bucket']})
                entries=list(c.execute(select(documents.c.kind,documents.c.id,documents.c.data).where(documents.c.kind.in_(['catalog','change','intake','section','history']),documents.c.data['document_id'].as_string().in_(wanted))).all())
                for kind,key,row in entries:
                    if row['document_id'] in wanted:c.execute(delete(documents).where(documents.c.kind==kind,documents.c.id==key))
                result={'deleted_document_ids':[row['document_id'] for row in rows]};self.record(c,actor,operation,'batch',result)
            self.flush_document_deletions()
            return result,None
        with self.engine.connect() as c:
            if operation=='get_documents':return {'documents':[self.doc_wire(row) for row in self.find_documents(c,p['document_ids'])]},None
            kind,key={'get_change_request_documents':('change','change_request_id'),'get_intake_form_documents':('intake','submission_id'),'get_section_documents':('section','internal_record_id')}[operation]
            target=p[key]
            if kind=='intake':
                try:target=str(uuid.UUID(target))
                except (ValueError,TypeError,AttributeError):raise RegistryError('SYS-ERR-001') from None
            links=list(c.execute(select(documents.c.data).where(documents.c.kind==kind,documents.c.state=='READY',documents.c.data[key].as_string()==target).order_by(documents.c.position)).scalars())
            ids={link['document_id'] for link in links}
            catalog={row['document_id']:row for row in c.execute(select(documents.c.data).where(documents.c.kind=='catalog',documents.c.state=='READY',documents.c.id.in_(ids))).scalars()};output=[]
            for link in links:
                if link[key]==target and link['document_id'] in catalog:output.append(self.doc_wire(catalog[link['document_id']],link.get('section_id'),link.get('label')))
            return {key:p[key],'documents':output},None
