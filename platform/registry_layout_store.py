"""Custom register console tabs, sections, links and UI-schema operations."""
import uuid,re
from sqlalchemy import MetaData,Table,Column,String,JSON,Integer,select,insert,update,delete,func
from registry_configuration_store import RegistryConfigurationStore
from registry_metadata_store import RegistryError

metadata=MetaData()
layouts=Table('console_register_layouts',metadata,Column('kind',String,primary_key=True),Column('id',String,primary_key=True),Column('data',JSON,nullable=False),Column('position',Integer,nullable=False))
SUPPORTED_PATHS=frozenset(
    ['/register-tab-metadata/'+name for name in ['create_tab','delete_tab','get_all_tabs','get_tab','update_tab','add_section','get_sections','update_section','remove_section']]
    +['/register-section-metadata/'+name for name in ['create_section','delete_section','get_all_sections_brief','get_all_sections','get_section','update_section','update_section_ui_schema','get_section_ui_schema']])
KEYS={'section':'section_id','tab':'tab_id','link':'tab_section_id','intake-link':'tab_section_id','intake-tab':'tab_id'}

class RegistryLayoutStore(RegistryConfigurationStore):
    def initialize(self):super().initialize();metadata.create_all(self.engine)
    def seed_layouts(self,dataset):
        with self.write() as c:
            if c.execute(select(layouts.c.id).where(layouts.c.kind.in_(list(dataset)))).first():raise RuntimeError('Refusing to overwrite layouts')
            for kind,rows in dataset.items():
                for position,row in enumerate(rows):c.execute(insert(layouts).values(kind=kind,id=row[KEYS[kind]],data=row,position=position))
    def rows(self,c,kind):return [dict(x) for x in c.execute(select(layouts.c.data).where(layouts.c.kind==kind).order_by(layouts.c.position)).scalars()]
    def require_register(self,c,key):
        row=self.definition(c,'register',key)
        if row is None:raise RegistryError('SYS-ERR-001')
        return row
    def layout(self,c,kind,key,register=None):
        row=c.execute(select(layouts.c.data).where(layouts.c.kind==kind,layouts.c.id==key)).scalar_one_or_none()
        if row is None or register is not None and row.get('register_id')!=register:raise RegistryError('SYS-ERR-001')
        return dict(row)
    def put(self,c,kind,row,create=False):
        key=row[KEYS[kind]]
        if kind=='tab' and row.get('tab_label') and not re.match(r'^[a-z][a-z0-9_]*$',row['tab_label']):raise RegistryError('SYS-ERR-001')
        if create:
            position=(c.execute(select(func.max(layouts.c.position))).scalar_one() or 0)+1
            c.execute(insert(layouts).values(kind=kind,id=key,data=row,position=position))
        else:c.execute(update(layouts).where(layouts.c.kind==kind,layouts.c.id==key).values(data=row))
    def remove(self,c,kind,key):c.execute(delete(layouts).where(layouts.c.kind==kind,layouts.c.id==key))
    def relation(self,c,parent_id,child_id):
        parent=self.require_register(c,parent_id);child=self.require_register(c,child_id)
        if parent_id==child_id:return 'SELF'
        if child.get('master_register_id')==parent_id:return 'DESCENDANT'
        current=child_id;seen=set();intermediate_register=False
        for depth in range(20):
            if not current or current in seen:break
            seen.add(current);node=self.definition(c,'register',current)
            if node is None:break
            current=node.get('master_register_id')
            if depth==0:continue
            if node['register_id']==parent_id:return 'DESCENDANT_OF_A_REGISTER' if intermediate_register else 'DESCENDANT'
            intermediate_register=intermediate_register or node['register_purpose']=='REGISTER'
            if current==parent_id:return 'DESCENDANT_OF_A_REGISTER' if intermediate_register else 'DESCENDANT'
        if parent.get('master_register_id')==child_id:return 'ANCESTOR'
        if parent.get('master_register_id') and parent.get('master_register_id')==child.get('master_register_id'):return 'PEER'
        return 'SELF'
    def section_wire(self,c,row,brief=False,relation_root=None):
        definition=self.require_register(c,row['section_register_id'])
        result=dict(row)
        result['section_ui_schema']=None if brief else row.get('section_ui_schema')
        result['register_purpose']=None if brief else definition['register_purpose']
        result['register_relation']=None if brief else self.relation(c,relation_root or row['register_id'],row['section_register_id'])
        return self.models.model('G2PRegisterSectionData').model_validate(result).model_dump(mode='json')
    def link_wire(self,c,row):
        result=dict(row);section=self.layout(c,'section',row['section_id'],row['register_id'])
        result['section_data']=self.section_wire(c,section)
        return self.models.model('G2PRegisterUITabSectionData').model_validate(result).model_dump(mode='json')
    def page(self,rows,pagination,always=False):
        total=len(rows)
        if pagination:
            size=pagination['page_size'];start=(pagination['current_page']-1)*size
            return rows[start:start+size],{'number_of_items':total,'number_of_pages':(total+size-1)//size}
        return rows,{'number_of_items':total,'number_of_pages':1} if always else None
    def execute_request(self,path,p,actor,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_request(path,p,actor,pagination)
        operation=path.rsplit('/',1)[-1];section_path=path.startswith('/register-section-metadata/')
        reading=operation.startswith('get_')
        with (self.engine.connect() if reading else self.write()) as c:
            if section_path:
                if operation.startswith('get_all_sections'):
                    self.require_register(c,p['register_id'])
                    rows=sorted([row for row in self.rows(c,'section') if row['register_id']==p['register_id']],key=lambda row:row['section_mnemonic'])
                    brief=operation.endswith('_brief')
                    selected,page=self.page(rows,None if brief else pagination,always=not brief)
                    return [self.section_wire(c,row,brief) for row in selected],page
                if operation=='create_section':
                    self.require_register(c,p['register_id']);self.require_register(c,p['section_register_id'])
                    fields=set(self.models.definitions['G2PRegisterSectionData']['properties'])-{'section_id'}
                    row={field:p.get(field) for field in fields};row['section_id']=str(uuid.uuid4());row['is_core_section']=bool(p.get('is_core_section'))
                    self.put(c,'section',row,True);result={'section_id':row['section_id']}
                else:
                    row=self.layout(c,'section',p['section_id'],p.get('register_id') if operation in {'get_section','get_section_ui_schema','update_section_ui_schema'} else None)
                    if operation=='get_section':return self.section_wire(c,row),None
                    if operation=='get_section_ui_schema':return {'section_id':row['section_id'],'section_ui_schema':row.get('section_ui_schema')},None
                    if operation=='delete_section':
                        if any(link['section_id']==row['section_id'] for kind in ['link','intake-link'] for link in self.rows(c,kind)):
                            raise RegistryError('SECTION_CURRENTLY_USED','SECTION_CURRENTLY_USED')
                        self.remove(c,'section',row['section_id']);result=None
                    else:
                        if operation=='update_section_ui_schema':row['section_ui_schema']=p.get('section_ui_schema')
                        elif operation=='update_section':
                            if p.get('section_register_id') is not None:self.require_register(c,p['section_register_id'])
                            row.update({field:p[field] for field in row if field not in {'section_id','register_id','section_ui_schema'} and p.get(field) is not None})
                        else:raise KeyError(path)
                        self.put(c,'section',row);result={'section_id':row['section_id']}
                key=row['section_id']
            else:
                if operation=='get_all_tabs':
                    register=p.get('register_id')
                    if register is not None:self.require_register(c,register)
                    rows=[row for row in self.rows(c,'tab') if register is None or row['register_id']==register]
                    rows.sort(key=lambda row:(row['tab_order'],row['tab_label']))
                    return self.page(rows,pagination,always=True)
                if operation=='create_tab':
                    self.require_register(c,p['register_id'])
                    row={field:p[field] for field in ['register_id','tab_label','tab_order','is_active']};row['tab_id']=str(uuid.uuid4())
                    self.put(c,'tab',row,True);result={'tab_id':row['tab_id']};key=row['tab_id']
                elif operation in {'get_tab','update_tab','delete_tab','add_section','get_sections'}:
                    tab=self.layout(c,'tab',p['tab_id'],p.get('register_id') if operation=='add_section' else None)
                    if operation=='get_tab':return tab,None
                    if operation=='get_sections':
                        links=sorted([row for row in self.rows(c,'link') if row['tab_id']==tab['tab_id']],key=lambda row:(row['section_order'],row['tab_section_id']))
                        links,_=self.page(links,pagination)
                        return [self.link_wire(c,row) for row in links],None
                    if operation=='add_section':
                        self.layout(c,'section',p['section_id'],tab['register_id'])
                        if any(row['tab_id']==tab['tab_id'] and row['section_id']==p['section_id'] for row in self.rows(c,'link')):raise RegistryError('SYS-ERR-001')
                        row={'tab_section_id':str(uuid.uuid4()),'register_id':tab['register_id'],'tab_id':tab['tab_id'],'section_id':p['section_id'],'section_order':p['section_order']}
                        self.put(c,'link',row,True);key=row['tab_section_id'];result={'tab_section_id':key}
                    else:
                        key=tab['tab_id']
                        if operation=='delete_tab':
                            for row in self.rows(c,'link'):
                                if row['tab_id']==key:self.remove(c,'link',row['tab_section_id'])
                            self.remove(c,'tab',key);result=None
                        else:
                            tab.update({field:p[field] for field in ['tab_label','tab_order','is_active'] if p.get(field) is not None})
                            self.put(c,'tab',tab);result={'tab_id':key}
                else:
                    row=self.layout(c,'link',p['tab_section_id']);key=row['tab_section_id']
                    if operation=='remove_section':self.remove(c,'link',key);result=None
                    elif operation=='update_section':
                        if p.get('section_id') is not None:self.layout(c,'section',p['section_id'],row['register_id'])
                        row.update({field:p[field] for field in ['section_id','section_order'] if p.get(field) is not None})
                        self.put(c,'link',row);result=self.link_wire(c,row)
                    else:raise KeyError(path)
            self.record(c,actor,operation,key,result)
            return result,None
