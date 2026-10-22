"""Custom form definitions, form layouts and rendered intake-form metadata."""
import uuid
from sqlalchemy import select,insert,update,delete,func
from registry_configuration_store import catalog
from registry_layout_store import RegistryLayoutStore
from registry_metadata_store import RegistryError

SUPPORTED_PATHS=frozenset('/intake-form-metadata/'+name for name in ['create_intake_form','get_intake_form','render_intake_form','get_all_intake_forms','update_intake_form','delete_intake_form','create_tab','get_tab','get_all_tabs','update_tab','delete_tab','add_section','get_all_sections','update_section','remove_section'])

class RegistryIntakeMetadataStore(RegistryLayoutStore):
    def forms(self,c):return [dict(row) for row in c.execute(select(catalog.c.data).where(catalog.c.kind=='form').order_by(catalog.c.position)).scalars()]
    def form(self,c,key):
        row=self.definition(c,'form',key)
        if row is None:raise RegistryError('SYS-ERR-001')
        return dict(row)
    def put_form(self,c,row,create=False):
        if any(other['form_mnemonic']==row['form_mnemonic'] and other['form_id']!=row['form_id'] for other in self.forms(c)):raise RegistryError('SYS-ERR-001')
        if create:
            position=(c.execute(select(func.max(catalog.c.position))).scalar_one() or 0)+1
            c.execute(insert(catalog).values(kind='form',id=row['form_id'],data=row,position=position))
        else:c.execute(update(catalog).where(catalog.c.kind=='form',catalog.c.id==row['form_id']).values(data=row))
    def form_wire(self,c,row):
        result=dict(row);register=self.definition(c,'register',row['register_id'])
        result['register_mnemonic']=register['register_mnemonic'] if register else None
        return self.models.model('IntakeFormDefinitionData').model_validate(result).model_dump(mode='json')
    def render(self,c,form):
        result=dict(form);tabs=[tab for tab in self.rows(c,'intake-tab') if tab['form_id']==form['form_id']]
        tabs.sort(key=lambda row:row['tab_order']);rendered=[]
        sections={row['section_id']:row for row in self.rows(c,'section')}
        for tab in tabs:
            output=dict(tab);output['sections']=[]
            links=sorted([row for row in self.rows(c,'intake-link') if row['tab_id']==tab['tab_id']],key=lambda row:row['section_order'])
            for link in links:
                section=sections.get(link['section_id'])
                if section is None:continue
                item=self.section_wire(c,section,relation_root=form['register_id'])
                item.update(tab_section_id=link['tab_section_id'],section_order=link['section_order'])
                output['sections'].append(item)
            rendered.append(output)
        result['tabs']=rendered
        return self.models.model('IntakeFormRenderedData').model_validate(result).model_dump(mode='json')
    def execute_request(self,path,p,actor,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_request(path,p,actor,pagination)
        operation=path.rsplit('/',1)[-1];reading=operation.startswith('get_') or operation=='render_intake_form'
        with (self.engine.connect() if reading else self.write()) as c:
            if operation=='get_all_intake_forms':
                if p.get('register_id') is not None:self.require_register(c,p['register_id'])
                rows=[row for row in self.forms(c) if (p.get('register_id') is None or row['register_id']==p['register_id']) and (p.get('used_only_in_ingestion_pipeline') is None or row['used_only_in_ingestion_pipeline']==p['used_only_in_ingestion_pipeline'])]
                rows.sort(key=lambda row:(row['form_mnemonic'],row['form_id']));rows,page=self.page(rows,pagination)
                return [self.form_wire(c,row) for row in rows],page
            if operation=='create_intake_form':
                definition=self.require_register(c,p['register_id'])
                if definition['register_purpose']!='REGISTER':raise RegistryError('SYS-ERR-001')
                row={key:p[key] for key in ['register_id','form_mnemonic','form_description','number_of_verifications','used_only_in_ingestion_pipeline']};row['form_id']=str(uuid.uuid4())
                self.put_form(c,row,True);result={'form_id':row['form_id']};key=row['form_id']
            elif operation in {'get_intake_form','render_intake_form','update_intake_form','delete_intake_form'}:
                row=self.form(c,p['form_id']);key=row['form_id']
                if operation=='get_intake_form':return self.form_wire(c,row),None
                if operation=='render_intake_form':return self.render(c,row),None
                if operation=='delete_intake_form':
                    tabs={tab['tab_id'] for tab in self.rows(c,'intake-tab') if tab['form_id']==key}
                    for link in self.rows(c,'intake-link'):
                        if link['tab_id'] in tabs:self.remove(c,'intake-link',link['tab_section_id'])
                    for tab in tabs:self.remove(c,'intake-tab',tab)
                    c.execute(delete(catalog).where(catalog.c.kind=='form',catalog.c.id==key));result=None
                else:
                    row.update({field:p[field] for field in ['form_mnemonic','form_description','number_of_verifications','used_only_in_ingestion_pipeline'] if p.get(field) is not None})
                    self.put_form(c,row);result={'form_id':key}
            elif operation=='get_all_tabs':
                form=p.get('form_id')
                if form is not None:self.form(c,form)
                rows=[row for row in self.rows(c,'intake-tab') if form is None or row['form_id']==form]
                rows.sort(key=lambda row:(row['tab_order'],row['tab_label'],row['tab_id']))
                return self.page(rows,pagination)
            elif operation=='create_tab':
                self.form(c,p['form_id']);row={key:p[key] for key in ['form_id','tab_label','tab_order']};row['tab_id']=str(uuid.uuid4())
                self.put(c,'intake-tab',row,True);key=row['tab_id'];result={'tab_id':key}
            elif operation in {'get_tab','update_tab','delete_tab'}:
                row=self.layout(c,'intake-tab',p['tab_id']);key=row['tab_id']
                if operation=='get_tab':return row,None
                if operation=='delete_tab':
                    for link in self.rows(c,'intake-link'):
                        if link['tab_id']==key:self.remove(c,'intake-link',link['tab_section_id'])
                    self.remove(c,'intake-tab',key);result=None
                else:
                    row.update({field:p[field] for field in ['tab_label','tab_order'] if p.get(field) is not None});self.put(c,'intake-tab',row);result={'tab_id':key}
            elif operation=='get_all_sections':
                tab=p.get('tab_id')
                if tab is not None:self.layout(c,'intake-tab',tab)
                rows=[row for row in self.rows(c,'intake-link') if tab is None or row['tab_id']==tab]
                rows.sort(key=lambda row:(row['section_order'],row['tab_section_id']));rows,page=self.page(rows,pagination)
                sections={row['section_id']:row for row in self.rows(c,'section')}
                for row in rows:row['section_mnemonic']=sections.get(row['section_id'],{}).get('section_mnemonic')
                return rows,page
            elif operation=='add_section':
                self.layout(c,'intake-tab',p['tab_id']);self.layout(c,'section',p['section_id'])
                if any(row['tab_id']==p['tab_id'] and row['section_id']==p['section_id'] for row in self.rows(c,'intake-link')):raise RegistryError('SYS-ERR-001')
                row={field:p[field] for field in ['tab_id','section_id','section_order']};row['tab_section_id']=str(uuid.uuid4())
                self.put(c,'intake-link',row,True);key=row['tab_section_id'];result={'tab_section_id':key}
            else:
                row=self.layout(c,'intake-link',p['tab_section_id']);key=row['tab_section_id']
                if operation=='remove_section':self.remove(c,'intake-link',key);result=None
                elif operation=='update_section':
                    if p.get('section_order') is not None:row['section_order']=p['section_order']
                    self.put(c,'intake-link',row);result={'tab_section_id':key}
                else:raise KeyError(path)
            self.record(c,actor,operation,key,result)
            return result,None
