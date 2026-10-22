"""Custom register definitions, schema settings and field metadata.

Field descriptions and historical has-data flags are captured interface/data
snapshots; current record writes must update has_data in the same transaction.
"""
import uuid
from sqlalchemy import MetaData,Table,Column,String,JSON,select,insert,update,delete,func
from registry_configuration_store import catalog
from registry_intake_metadata_store import RegistryIntakeMetadataStore
from registry_metadata_store import RegistryError,image_value

metadata=MetaData()
states=Table('console_register_definition_state',metadata,Column('id',String,primary_key=True),Column('data',JSON,nullable=False))
SUPPORTED_PATHS=frozenset('/register-metadata/'+name for name in ['create_register','edit_register','delete_register','get_all_registers','get_dashboard_registers','get_child_registers','get_master_register','get_register_fields','get_register_schema','update_register_schema','update_dedup_is_enabled','update_dedup_threshold_score','update_deduplication_schema','update_search_result_schema'])
SCHEMA_FIELDS=['deduplicate_schema','search_result_schema','filter_schema']

class RegistryDefinitionStore(RegistryIntakeMetadataStore):
    def initialize(self):super().initialize();metadata.create_all(self.engine)
    def state(self,c,key):return dict(c.execute(select(states.c.data).where(states.c.id==key)).scalar_one_or_none() or {'has_data':False,'fields':None,'schema':None})
    def save_state(self,c,key,data,new=False):
        if new:c.execute(insert(states).values(id=key,data=data))
        else:c.execute(update(states).where(states.c.id==key).values(data=data))
    def definitions(self,c):return [dict(row) for row in c.execute(select(catalog.c.data).where(catalog.c.kind=='register').order_by(catalog.c.position)).scalars()]
    def require_definition(self,c,key):
        row=self.definition(c,'register',key)
        if row is None:raise RegistryError('REG-ERR-001','REGISTER_NOT_FOUND')
        return dict(row)
    def save_definition(self,c,row,new=False):
        if any(other['register_mnemonic']==row['register_mnemonic'] and other['register_id']!=row['register_id'] for other in self.definitions(c)):raise RegistryError('SYS-ERR-001')
        if new:
            position=(c.execute(select(func.max(catalog.c.position))).scalar_one() or 0)+1
            c.execute(insert(catalog).values(kind='register',id=row['register_id'],data=row,position=position))
        else:c.execute(update(catalog).where(catalog.c.kind=='register',catalog.c.id==row['register_id']).values(data=row))
    def register_wire(self,row,mode='full'):
        fields=set(self.models.definitions['RegisterData']['properties'])
        if mode in {'limited','delete'}:
            fields={'register_id','register_mnemonic','register_subject','register_description','master_register_id','functional_id_generation_required','outgest_applicable'}
            if mode=='delete':fields|={'register_purpose','register_rank','register_icon'}
        return self.models.model('RegisterData').model_validate({key:row[key] for key in fields if key in row}).model_dump(mode='json')
    def schema_wire(self,key,state):return {'register_id':key,**(state.get('schema') or {field:None for field in SCHEMA_FIELDS})}
    def execute_request(self,path,p,actor,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_request(path,p,actor,pagination)
        operation=path.rsplit('/',1)[-1];reading=operation.startswith('get_')
        with (self.engine.connect() if reading else self.write()) as c:
            if operation in {'get_all_registers','get_dashboard_registers'}:
                rows=self.definitions(c)
                if operation=='get_dashboard_registers':
                    rows=sorted([row for row in rows if row['register_purpose']=='REGISTER'],key=lambda row:(row.get('register_rank') is None,row.get('register_rank')))
                    return [self.register_wire(row,'limited') for row in rows],None
                pagination=pagination or {'current_page':1,'page_size':10};sort=pagination.get('sort_by') or 'register_rank';reverse=sort.startswith('-');sort=sort.removeprefix('-')
                if sort not in (rows[0] if rows else {}):sort='register_rank';reverse=False
                rows.sort(key=lambda row:(row.get(sort) is None,row.get(sort)),reverse=reverse)
                selected,page=self.page(rows,pagination);result=[]
                for row in selected:
                    value=dict(row);master=self.definition(c,'register',row.get('master_register_id'))
                    value['master_register_mnemonic']=master['register_mnemonic'] if master else None
                    value['has_data']=self.state(c,row['register_id'])['has_data']
                    result.append(self.models.model('AllRegistersRegisterData').model_validate(value).model_dump(mode='json'))
                return result,page
            if operation=='create_register':
                if p.get('master_register_id'):self.require_register(c,p['master_register_id'])
                row=dict(p);key=str(uuid.uuid4());mnemonic=p['register_mnemonic']
                row.update(register_id=key,register_subject=(mnemonic[0].upper()+mnemonic[1:]+'s') if mnemonic else None,register_purpose=p.get('register_purpose') or 'REGISTER',register_icon=image_value(p['register_icon']) if p.get('register_icon') else None,has_image=False,program_id=None,program_mnemonic=None)
                self.save_definition(c,row,True);self.save_state(c,key,{'has_data':False,'fields':None,'schema':{field:None for field in SCHEMA_FIELDS}},True)
                result=self.register_wire(row)
            else:
                key=p['register_id']
                if operation in {'update_dedup_is_enabled','update_dedup_threshold_score'}:
                    row=self.definition(c,'register',key)
                    if row is None:raise RegistryError('SYS-ERR-001')
                    row=dict(row)
                else:row=self.require_definition(c,key)
                state=self.state(c,key)
                if operation=='get_child_registers':
                    return [self.models.model('ChildRegisterData').model_validate(item).model_dump(mode='json') for item in self.definitions(c) if item.get('master_register_id')==key],None
                if operation=='get_master_register':
                    master=self.definition(c,'register',row.get('master_register_id'))
                    return self.register_wire(master,'limited') if master else None,None
                if operation=='get_register_schema':return self.schema_wire(key,state),None
                if operation=='get_register_fields':
                    interface=self.definition(c,'field-interface',row['register_purpose']+':'+row['register_mnemonic']) or {}
                    if interface.get('fields') is None:
                        error=interface.get('fields_error') or ({'code':'SYS-ERR-001','message':'UNEXPECTED_ERROR'} if row['register_purpose']=='CORE_TABLE' else {'code':'REG-ERR-002','message':'Register implementation not found for '+row['register_mnemonic']})
                        raise RegistryError(error['code'],error['message'])
                    size=(pagination or {}).get('page_size',10);count=len(interface['fields'])
                    return {'register_id':key,'register_mnemonic':row['register_mnemonic'],'fields':interface['fields']},{'number_of_items':count,'number_of_pages':(count+size-1)//size}
                if operation=='delete_register':
                    if state['has_data']:raise RegistryError('REQ-VAL-000',f"Cannot delete register '{row['register_mnemonic']}' as it has existing data.")
                    c.execute(delete(states).where(states.c.id==key));c.execute(delete(catalog).where(catalog.c.kind=='register',catalog.c.id==key));result=self.register_wire(row,'delete')
                elif operation=='edit_register':
                    fields=set(row)-{'register_id','register_subject','has_image','program_id','program_mnemonic'}
                    if state['has_data']:fields-={'register_mnemonic','master_register_id','register_purpose','functional_id_generation_required'}
                    icon_update=p.get('register_icon') is not None
                    icon=image_value(p['register_icon']) if p.get('register_icon') else None
                    if not state['has_data'] and p.get('master_register_id') is not None:
                        if p['master_register_id']==key:raise RegistryError('SYS-ERR-001')
                        self.require_register(c,p['master_register_id'])
                    for field in fields:
                        if field=='register_icon':
                            if icon_update:row[field]=icon
                        elif p.get(field) is not None:row[field]=p[field]
                    if p.get('register_mnemonic') is not None and 'register_mnemonic' in fields:
                        mnemonic=row['register_mnemonic']
                        if mnemonic:row['register_subject']=mnemonic[0].upper()+mnemonic[1:]+'s'
                    self.save_definition(c,row);result=self.register_wire(row)
                elif operation in {'update_dedup_is_enabled','update_dedup_threshold_score'}:
                    field='dedup_is_enabled' if operation.endswith('is_enabled') else 'dedup_threshold_score'
                    row[field]=p[field];self.save_definition(c,row);result=self.schema_wire(key,state)
                else:
                    if state.get('schema') is None:raise RegistryError('SYS-ERR-001')
                    fields=SCHEMA_FIELDS if operation=='update_register_schema' else (['deduplicate_schema'] if operation=='update_deduplication_schema' else ['search_result_schema'])
                    if operation not in {'update_register_schema','update_deduplication_schema','update_search_result_schema'}:raise KeyError(path)
                    state['schema'].update({field:p[field] for field in fields if p.get(field) is not None});self.save_state(c,key,state)
                    result={'register_id':key,**{field:p.get(field) for field in SCHEMA_FIELDS}} if operation=='update_register_schema' else self.schema_wire(key,state)
            self.record(c,actor,operation,key,result)
            return result,None
