"""Custom workflow and input configuration storage; no upstream imports.

The register/form/model catalog is a candidate snapshot until those metadata
operations themselves are migrated. This module is not a production database.
"""
import json,uuid
from pathlib import Path
from sqlalchemy import MetaData,Table,Column,String,JSON,Integer,select,insert,update,delete,func
from registry_metadata_store import RegistryMetadataStore,RegistryError
from registry_contract_models import ContractModels

metadata=MetaData()
catalog=Table('console_definition_catalog',metadata,Column('kind',String,primary_key=True),Column('id',String,primary_key=True),Column('data',JSON,nullable=False),Column('position',Integer,nullable=False))
configurations=Table('console_workflow_input_configs',metadata,Column('kind',String,primary_key=True),Column('id',String,primary_key=True),Column('data',JSON,nullable=False),Column('position',Integer,nullable=False))
KINDS={
    'awe':('awe_policy_config_id','AwePolicyConfigurationData'),
    'vc':('vc_config_id','VcConfigurationData'),
    'import':('import_file_configuration_id','ImportFileConfigurationData'),
}
PREFIXES={'awe':'/awe-policy-config/','vc':'/input-mechanism-metadata/','import':'/input-mechanism-metadata/'}
SUPPORTED_PATHS=frozenset(
    ['/awe-policy-config/'+op+'_awe_policy_configuration' for op in ['create','get','update','delete']]
    +['/awe-policy-config/get_all_awe_policy_configurations']
    +['/input-mechanism-metadata/'+op for op in ['get_all_input_mechanisms','get_all_vc_configurations','get_vc_configuration_for_register','create_vc_configuration','update_vc_configuration','delete_vc_configuration','get_all_import_file_configurations','get_import_file_configuration_for_register','create_import_file_configuration','update_import_file_configuration','delete_import_file_configuration']])

class RegistryConfigurationStore(RegistryMetadataStore):
    def __init__(self,engine):
        super().__init__(engine)
        self.models=ContractModels(json.loads(Path(__file__).with_name('registry_full_contract.json').read_text()))
    def initialize(self):
        super().initialize();metadata.create_all(self.engine)
    def seed_configuration(self,data):
        with self.write() as c:
            if c.execute(select(catalog.c.id).where(catalog.c.kind.in_(['register','form','model','input']))).first() or c.execute(select(configurations.c.id)).first():
                raise RuntimeError('Refusing to overwrite configuration catalog')
            for kind,key in [('register','register_id'),('form','form_id'),('model','data_model_id'),('input','mechanism_id')]:
                for position,row in enumerate(data[kind]):c.execute(insert(catalog).values(kind=kind,id=row[key],data=row,position=position))
            for kind,(key,_) in KINDS.items():
                for position,row in enumerate(data[kind]):c.execute(insert(configurations).values(kind=kind,id=row[key],data=row,position=position))
    def definition(self,c,kind,key):
        return c.execute(select(catalog.c.data).where(catalog.c.kind==kind,catalog.c.id==key)).scalar_one_or_none()
    def register(self,c,key,mechanism=False):
        if self.definition(c,'register',key) is None:
            raise RegistryError('REG-ERR-001','REGISTER_NOT_FOUND' if mechanism else f'Register with id {key} not found')
    def validate_scope(self,row):
        scope=row['policy_scope'];form=row.get('intake_form_id');section=row.get('section_id')
        form=None if isinstance(form,str) and not form.strip() else form
        section=None if isinstance(section,str) and not section.strip() else section
        message=None
        if scope not in {'REGISTER','INTAKE_FORM','SECTION'}:message=f"Invalid policy_scope '{scope}'. Expected one of: REGISTER, INTAKE_FORM, SECTION"
        elif scope=='REGISTER' and (form is not None or section is not None):message='For REGISTER scope, intake_form_id and section_id must be omitted'
        elif scope=='INTAKE_FORM' and not form:message='For INTAKE_FORM scope, intake_form_id is required'
        elif scope=='INTAKE_FORM' and section is not None:message='For INTAKE_FORM scope, section_id must be omitted'
        elif scope=='SECTION' and not section:message='For SECTION scope, section_id is required'
        if message:raise RegistryError('REQ-VAL-000',message)
    def fetch(self,c,kind,key):
        data=c.execute(select(configurations.c.data).where(configurations.c.kind==kind,configurations.c.id==key)).scalar_one_or_none()
        if data is None:
            code,label={'awe':('AWE-ERR-001','AWE policy configuration'),'vc':('VCF-ERR-001','VC configuration'),'import':('IF-ERR-001','Import file configuration')}[kind]
            raise RegistryError(code,f'{label} with id {key} not found')
        return dict(data)
    def wire(self,kind,row,joins=False,c=None):
        row=dict(row)
        if kind=='vc' and joins:
            form=self.definition(c,'form',row.get('intake_form_id'));model=self.definition(c,'model',row.get('data_model_id'))
            row['intake_form_mnemonic']=form.get('form_mnemonic') if form else None
            row['data_model_mnemonic']=model.get('data_model_mnemonic') if model else None
        return self.models.model(KINDS[kind][1]).model_validate(row).model_dump(mode='json')
    def execute_request(self,path,p,actor,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute(path,p,actor),None
        operation=path.rsplit('/',1)[-1];reading=operation.startswith('get_')
        with (self.engine.connect() if reading else self.write()) as c:
            if operation=='get_all_input_mechanisms':
                self.register(c,p['register_id'],mechanism=True)
                rows=c.execute(select(catalog.c.data).where(catalog.c.kind=='input').order_by(catalog.c.position)).scalars()
                return [row for row in rows if row['register_id']==p['register_id']],None
            kind='awe' if path.startswith('/awe-policy-config/') else ('vc' if 'vc_configuration' in operation else 'import')
            key_field,_=KINDS[kind]
            is_list=operation.startswith('get_all_') or operation.endswith('_for_register')
            if is_list:
                register=p.get('register_id')
                if operation.endswith('_for_register') or (kind=='vc' and register):self.register(c,register)
                rows=[dict(row) for row in c.execute(select(configurations.c.data).where(configurations.c.kind==kind).order_by(configurations.c.position)).scalars()]
                if kind=='vc' and register or operation.endswith('_for_register'):rows=[row for row in rows if row['register_id']==register]
                if kind=='awe':rows.sort(key=lambda row:(row['register_id'],row['policy_scope'],row[key_field]))
                total=len(rows);page=None
                if pagination:
                    size=pagination['page_size'];start=(pagination['current_page']-1)*size
                    rows=rows[start:start+size];page={'number_of_items':total,'number_of_pages':(total+size-1)//size}
                return [self.wire(kind,row,joins=kind=='vc',c=c) for row in rows],page
            if operation.startswith('get_'):return self.wire(kind,self.fetch(c,kind,p[key_field])),None
            if operation.startswith('create_'):
                self.register(c,p.get('register_id'))
                fields={'awe':['policy_scope','register_id','intake_form_id','section_id','policy_type','policy_key','context_field_names'],
                        'vc':['register_id','intake_form_id','data_model_id','vc_mnemonic','descriptor_schema'],
                        'import':['register_id','form_id','data_model_id','import_file_template_mnemonic','import_file_template_description']}[kind]
                row={field:p.get(field) for field in fields};row[key_field]=str(uuid.uuid4())
                if kind=='awe':self.validate_scope(row)
                self.wire(kind,row)
                position=(c.execute(select(func.max(configurations.c.position))).scalar_one() or 0)+1
                c.execute(insert(configurations).values(kind=kind,id=row[key_field],data=row,position=position))
            else:
                row=self.fetch(c,kind,p.get(key_field));key=row[key_field]
                if operation.startswith('delete_'):c.execute(delete(configurations).where(configurations.c.kind==kind,configurations.c.id==key))
                elif operation.startswith('update_'):
                    excluded={key_field}
                    if kind!='awe':excluded.add('register_id')
                    fields=set(self.models.definitions[KINDS[kind][1]]['properties'])-excluded-{'intake_form_mnemonic','data_model_mnemonic'}
                    row.update({field:p[field] for field in fields if p.get(field) is not None})
                    if kind=='awe':
                        if p.get('register_id') is not None:self.register(c,p['register_id'])
                        self.validate_scope(row)
                    self.wire(kind,row)
                    c.execute(update(configurations).where(configurations.c.kind==kind,configurations.c.id==key).values(data=row))
                else:raise KeyError(path)
            result=None if kind=='awe' and operation.startswith('delete_') else self.wire(kind,row)
            if kind!='awe':result=[result]
            self.record(c,actor,operation,row[key_field],result)
            return result,None
