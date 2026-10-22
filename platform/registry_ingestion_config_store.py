"""Custom incoming key-path and semantic-pattern configuration operations."""
import json,uuid
from pathlib import Path
from sqlalchemy import MetaData,Table,Column,String,JSON,Integer,select,insert,update,delete,func
from registry_definition_store import RegistryDefinitionStore
from registry_metadata_store import RegistryError

metadata=MetaData()
patterns=Table('console_ingestion_patterns',metadata,Column('kind',String,primary_key=True),Column('id',String,primary_key=True),Column('data',JSON,nullable=False),Column('position',Integer,nullable=False))
KINDS={'key':('key_path_id','IncomingModelKeyPathData','incoming_key_path','incoming_key_paths'),
       'semantic':('semantic_pattern_id','IncomingModelSemanticPatternData','semantic_pattern','semantic_patterns'),
       'register':('register_semantic_pattern_id','IncomingModelRegisterSemanticPatternData','register_semantic_pattern','register_semantic_patterns')}
SUPPORTED_PATHS=frozenset('/ingestion-config/'+operation+'_'+(plural if operation=='get_all' else singular) for _,(_,_,singular,plural) in KINDS.items() for operation in ['create','get','get_all','update','delete'])

class RegistryIngestionConfigStore(RegistryDefinitionStore):
    def initialize(self):super().initialize();metadata.create_all(self.engine)
    def fail(self,name,message=None):
        error=json.loads(Path(__file__).with_name('registry_error_contract.json').read_text())[name]
        raise RegistryError(error['code'],message or error['message'])
    def incoming_rows(self,c,kind):return [dict(row) for row in c.execute(select(patterns.c.data).where(patterns.c.kind==kind).order_by(patterns.c.position)).scalars()]
    def seed_patterns(self,dataset):
        with self.write() as c:
            if c.execute(select(patterns.c.id)).first():raise RuntimeError('Refusing to overwrite incoming patterns')
            for kind,rows in dataset.items():
                for position,row in enumerate(rows):c.execute(insert(patterns).values(kind=kind,id=row[KINDS[kind][0]],data=row,position=position))
    def linked(self,c,kind,key):
        row=self.definition(c,kind,key)
        if row is None:self.fail({'model':'DATA_MODEL_NOT_FOUND','register':'REGISTER_NOT_FOUND','form':'INTAKE_FORM_NOT_FOUND'}[kind])
        return row
    def incoming_section(self,c,key,register):
        row=next((row for row in self.rows(c,'section') if row['section_id']==key),None)
        if row is None or row['register_id']!=register:self.fail('INVALID_REQUEST','Section not found or does not belong to the specified register.')
        return row
    def pattern_wire(self,c,kind,row,listing=False):
        row=dict(row)
        if kind=='key':
            if listing:
                model=self.definition(c,'model',row['data_model_id'])
                return {'key_path_id':row['key_path_id'],'data_model_id':row['data_model_id'],'data_model_mnemonic':model['data_model_mnemonic'] if model else '','is_list':row['is_list']}
        else:
            model=self.linked(c,'model',row['data_model_id']);register=self.linked(c,'register',row['register_id'])
            row.update(data_model_mnemonic=model['data_model_mnemonic'],register_mnemonic=register['register_mnemonic'])
            if kind=='semantic':
                form=self.linked(c,'form',row['intake_form_id']);section=self.incoming_section(c,row['section_id'],row['register_id']) if row.get('section_id') else None
                row.update(intake_form_mnemonic=form['form_mnemonic'],section_mnemonic=section['section_mnemonic'] if section else None)
        return self.models.model(KINDS[kind][1]).model_validate(row).model_dump(mode='json')
    def get_pattern(self,c,kind,key):
        row=c.execute(select(patterns.c.data).where(patterns.c.kind==kind,patterns.c.id==key)).scalar_one_or_none()
        if row is None:self.fail('PATTERN_NOT_FOUND' if kind=='key' else 'SEMANTIC_PATTERN_NOT_FOUND','Register semantic pattern not found.' if kind=='register' else None)
        return dict(row)
    def execute_request(self,path,p,actor,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_request(path,p,actor,pagination)
        operation=path.rsplit('/',1)[-1];kind='key' if 'incoming_key_path' in operation else ('register' if 'register_semantic_pattern' in operation else 'semantic')
        field,_,_,_=KINDS[kind];reading=operation.startswith('get_')
        with (self.engine.connect() if reading else self.write()) as c:
            if operation.startswith('get_all_'):
                rows=sorted(self.incoming_rows(c,kind),key=lambda row:row[field]);rows,page=self.page(rows,pagination or {'current_page':1,'page_size':10})
                return [self.pattern_wire(c,kind,row,listing=True) for row in rows],page
            if operation.startswith('get_'):return self.pattern_wire(c,kind,self.get_pattern(c,kind,p[field])),None
            if operation.startswith('create_'):
                if kind=='key' and p.get(field) and any(row[field]==p[field] for row in self.incoming_rows(c,kind)):self.fail('PATTERN_ALREADY_EXISTS')
                self.linked(c,'model',p['data_model_id'])
                if kind=='key':
                    if any(row['data_model_id']==p['data_model_id'] for row in self.incoming_rows(c,kind)):self.fail('PATTERN_ALREADY_EXISTS_FOR_DATA_MODEL')
                else:
                    self.linked(c,'register',p['register_id'])
                    if kind=='semantic':
                        self.linked(c,'form',p['intake_form_id'])
                        if p.get('section_id'):self.incoming_section(c,p['section_id'],p['register_id'])
                fields=set(self.models.definitions[KINDS[kind][1]]['properties'])-{'data_model_mnemonic','register_mnemonic','intake_form_mnemonic','section_mnemonic'}
                row={key:p.get(key) for key in fields};row[field]=str(uuid.uuid4())
                if kind=='key' and row.get('key_path_for_list_elements') is None:raise RegistryError('SYS-ERR-001')
                if kind=='semantic':row['raw_payload_enricher_class']=p.get('raw_payload_enricher_class') or ''
                result=self.pattern_wire(c,kind,row)
                position=(c.execute(select(func.max(patterns.c.position))).scalar_one() or 0)+1
                c.execute(insert(patterns).values(kind=kind,id=row[field],data=row,position=position))
            else:
                row=self.get_pattern(c,kind,p[field])
                if operation.startswith('delete_'):
                    result=self.pattern_wire(c,kind,row);c.execute(delete(patterns).where(patterns.c.kind==kind,patterns.c.id==row[field]))
                elif operation.startswith('update_'):
                    if kind=='semantic' and p.get('section_id'):self.incoming_section(c,p['section_id'],row['register_id'])
                    fields=set(row)-{field,'data_model_id','register_id','intake_form_id'}
                    row.update({key:p[key] for key in fields if p.get(key) is not None})
                    result=self.pattern_wire(c,kind,row)
                    c.execute(update(patterns).where(patterns.c.kind==kind,patterns.c.id==row[field]).values(data=row))
                else:raise KeyError(path)
            self.record(c,actor,operation,row[field],result)
            return result,None
