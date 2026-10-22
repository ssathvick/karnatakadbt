"""Custom data-model and incoming/outgoing template configuration operations."""
import datetime,uuid
from sqlalchemy import MetaData,Table,Column,String,JSON,Integer,select,insert,update,delete,func
from registry_configuration_store import catalog
from registry_document_store import RegistryDocumentStore,documents
from registry_metadata_store import RegistryError

metadata=MetaData()
templates=Table('console_message_templates',metadata,Column('kind',String,primary_key=True),Column('id',String,primary_key=True),Column('data',JSON,nullable=False),Column('position',Integer,nullable=False))
SUPPORTED_PATHS=frozenset(['/data-model/'+name for name in ['create_data_model','get_data_model','get_all_data_models','update_data_model','delete_data_model']]+['/'+prefix+'/'+name for prefix in ['ingestion-config','outgestion-config'] for name in ['create_template','get_template','get_all_templates','update_template','delete_template']])

class RegistryMessageTemplateStore(RegistryDocumentStore):
    def initialize(self):super().initialize();metadata.create_all(self.engine)
    def model_rows(self,c):return [dict(row) for row in c.execute(select(catalog.c.data).where(catalog.c.kind=='model').order_by(catalog.c.position)).scalars()]
    def template_rows(self,c,kind):return [dict(row) for row in c.execute(select(templates.c.data).where(templates.c.kind==kind).order_by(templates.c.position)).scalars()]
    def seed_templates(self,data):
        with self.write() as c:
            if c.execute(select(templates.c.id)).first():raise RuntimeError('Refusing to overwrite message templates')
            for kind,rows in data.items():
                for position,row in enumerate(rows):c.execute(insert(templates).values(kind=kind,id=row['template_id'],data=row,position=position))
    def validate_template_document(self,c,key):
        if not key:self.fail('DOCUMENT_NOT_FOUND')
        row=c.execute(select(documents.c.data).where(documents.c.kind=='catalog',documents.c.state=='READY',documents.c.id==key,documents.c.data['bucket'].as_string()=='templates')).scalar_one_or_none()
        if row is None:self.fail('TEMPLATE_NOT_FOUND',f'TEMPLATE_NOT_FOUND: document_id={key}')
        return row
    def remove_template_document(self,c,key,cascade=False,strict=False):
        row=c.execute(select(documents.c.data).where(documents.c.kind=='catalog',documents.c.state=='READY',documents.c.id==key,documents.c.data['bucket'].as_string()=='templates')).scalar_one_or_none()
        if row is None:
            if strict:self.validate_template_document(c,key)
            return
        self.put_doc(c,'deletion',str(uuid.uuid4()),{'document_store_id':row['document_store_id'],'bucket':row['bucket']})
        entries=list(c.execute(select(documents.c.kind,documents.c.id,documents.c.data).where(documents.c.kind.in_(['catalog','change','intake','section','history'] if cascade else ['catalog']),documents.c.data['document_id'].as_string()==key)).all())
        for kind,record_id,data in entries:
            if data['document_id']==key:c.execute(delete(documents).where(documents.c.kind==kind,documents.c.id==record_id))
    def model(self,c,key):
        row=self.definition(c,'model',key)
        if row is None:self.fail('DATA_MODEL_NOT_FOUND')
        return dict(row)
    def model_wire(self,row):return self.models.model('DataModelData').model_validate(row).model_dump(mode='json')
    def template(self,c,kind,key):
        if not key:self.fail('INVALID_REQUEST')
        row=c.execute(select(templates.c.data).where(templates.c.kind==kind,templates.c.id==key)).scalar_one_or_none()
        if row is None:self.fail('TEMPLATE_NOT_FOUND')
        return dict(row)
    def template_wire(self,c,kind,row):
        result=dict(row);register=self.linked(c,'register',row['register_id']);model=self.linked(c,'model',row['data_model_id'])
        result.update(register_mnemonic=register['register_mnemonic'],data_model_mnemonic=model['data_model_mnemonic'])
        return self.models.model('IncomingTemplateData' if kind=='incoming' else 'OutgoingTemplateData').model_validate(result).model_dump(mode='json')
    def execute_request(self,path,p,actor,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_request(path,p,actor,pagination)
        operation=path.rsplit('/',1)[-1];reading=operation.startswith('get_')
        with (self.engine.connect() if reading else self.write()) as c:
            if path.startswith('/data-model/'):
                if operation=='get_all_data_models':
                    rows=sorted(self.model_rows(c),key=lambda row:row['data_model_id']);rows,page=self.page(rows,pagination or {'current_page':1,'page_size':10})
                    return [self.model_wire(row) for row in rows],page
                if operation=='get_data_model':return self.model_wire(self.model(c,p['data_model_id'])),None
                if operation=='create_data_model':
                    if any(row['data_model_mnemonic']==p['data_model_mnemonic'] for row in self.model_rows(c)):self.fail('DATA_MODEL_ALREADY_EXISTS')
                    if p.get('response_template_document_id'):self.validate_template_document(c,p['response_template_document_id'])
                    row={field:p.get(field) for field in self.models.definitions['DataModelData']['properties']};key=p.get('data_model_id') or str(uuid.uuid4());row['data_model_id']=key
                    position=(c.execute(select(func.max(catalog.c.position))).scalar_one() or 0)+1
                    c.execute(insert(catalog).values(kind='model',id=key,data=row,position=position));result=self.model_wire(row)
                else:
                    row=self.model(c,p['data_model_id']);key=row['data_model_id']
                    if operation=='delete_data_model':
                        result=self.model_wire(row)
                        if row.get('response_template_document_id'):self.remove_template_document(c,row['response_template_document_id'])
                        c.execute(delete(catalog).where(catalog.c.kind=='model',catalog.c.id==key))
                    elif operation=='update_data_model':
                        if p.get('data_model_mnemonic') is not None and p['data_model_mnemonic']!=row['data_model_mnemonic'] and any(other['data_model_mnemonic']==p['data_model_mnemonic'] for other in self.model_rows(c)):self.fail('DATA_MODEL_ALREADY_EXISTS')
                        if p.get('response_template_document_id') is not None:
                            replacement=p['response_template_document_id']
                            if replacement:self.validate_template_document(c,replacement)
                            if row.get('response_template_document_id') and row['response_template_document_id']!=replacement:self.remove_template_document(c,row['response_template_document_id'])
                        row.update({field:p[field] for field in ['data_model_mnemonic','pattern_for_data_model','response_template_document_id','is_active'] if p.get(field) is not None})
                        c.execute(update(catalog).where(catalog.c.kind=='model',catalog.c.id==key).values(data=row));result=self.model_wire(row)
                    else:raise KeyError(path)
            else:
                kind='incoming' if path.startswith('/ingestion-config/') else 'outgoing'
                if operation=='get_all_templates':
                    rows=sorted(self.template_rows(c,kind),key=lambda row:row['template_id']);rows,page=self.page(rows,pagination or {'current_page':1,'page_size':10})
                    return [self.template_wire(c,kind,row) for row in rows],page
                if operation=='get_template':return self.template_wire(c,kind,self.template(c,kind,p['template_id'])),None
                if operation=='create_template':
                    self.linked(c,'register',p['register_id']);self.linked(c,'model',p['data_model_id'])
                    if kind=='incoming' and (not p['data_model_id'] or not p['register_id']):self.fail('INVALID_REQUEST')
                    if any(row['register_id']==p['register_id'] and row['data_model_id']==p['data_model_id'] for row in self.template_rows(c,kind)):self.fail('TEMPLATE_ALREADY_EXISTS')
                    self.validate_template_document(c,p['template_document_id'])
                    fields=['register_id','data_model_id','template_document_id']+(['jsonld_expansion_required'] if kind=='incoming' else [])
                    row={field:p[field] for field in fields};key=str(uuid.uuid4());stamp=datetime.datetime.now(datetime.timezone.utc).isoformat();row.update(template_id=key,created_at=stamp,updated_at=stamp)
                    position=(c.execute(select(func.max(templates.c.position))).scalar_one() or 0)+1
                    c.execute(insert(templates).values(kind=kind,id=key,data=row,position=position));result=self.template_wire(c,kind,row)
                else:
                    row=self.template(c,kind,p['template_id']);key=row['template_id']
                    if operation=='delete_template':
                        result=self.template_wire(c,kind,row)
                        if row.get('template_document_id'):self.remove_template_document(c,row['template_document_id'],cascade=True,strict=True)
                        c.execute(delete(templates).where(templates.c.kind==kind,templates.c.id==key))
                    elif operation=='update_template':
                        if p.get('template_document_id') is not None:
                            replacement=p['template_document_id'];self.validate_template_document(c,replacement)
                            if row.get('template_document_id') and row['template_document_id']!=replacement:self.remove_template_document(c,row['template_document_id'],cascade=True,strict=True)
                            row['template_document_id']=replacement
                        if kind=='incoming' and p.get('jsonld_expansion_required') is not None:row['jsonld_expansion_required']=p['jsonld_expansion_required']
                        row['updated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
                        c.execute(update(templates).where(templates.c.kind==kind,templates.c.id==key).values(data=row));result=self.template_wire(c,kind,row)
                    else:raise KeyError(path)
            self.record(c,actor,operation,key,result)
        self.flush_document_deletions()
        return result,None
