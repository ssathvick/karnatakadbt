"""Own hierarchy traversal with policy checks and batched document enrichment."""
from sqlalchemy import select
from registry_awe_store import RegistryAweStore
from registry_record_store import records
from registry_row_store import rows
from registry_document_store import documents
from registry_metadata_api import RegistryPrincipal,RegistryAuthError
from registry_metadata_store import RegistryError

SUPPORTED_PATHS=frozenset('/register-data/'+name for name in ['get_section_records','get_tab_records','get_allowed_parents_for_a_child_section'])

class RegistryHierarchyStore(RegistryAweStore):
    def hierarchy_definition(self,definitions,key):
        if key not in definitions:self.fail('REGISTER_NOT_FOUND',f'Register with id {key} not found')
        return definitions[key]
    def hierarchy_interface(self,definition,field=None):
        interface=self.record_interface(definition)
        if not interface or not interface.get('current'):
            if definition['register_purpose']=='CORE_TABLE':raise RegistryError('SYS-ERR-001')
            self.fail('REGISTER_DATA_NOT_FOUND','Register implementation not found for '+definition['register_mnemonic'])
        columns=interface['current']['columns']
        if field and field not in columns:raise RegistryError('SYS-ERR-001')
        return interface
    def hierarchy_query(self,definition):
        self.hierarchy_interface(definition)
        return select(records.c.source_json).where(records.c.kind=='current',records.c.register_id==definition['register_id'])
    def hierarchy_subject(self,c,definition,key,policies=(),missing='record'):
        self.hierarchy_interface(definition,'internal_record_id');query=self.hierarchy_query(definition).where(records.c.record_id==key)
        original=c.execute(query).scalar_one_or_none()
        if original is None:
            message=f'Subject record {key} not found' if missing=='subject' else f"Record {key} not found in register {definition['register_mnemonic']}"
            self.fail('REGISTER_DATA_NOT_FOUND',message)
        if policies:
            condition=self.record_policy(definition,policies)
            if condition is not None and not c.execute(query.where(condition)).first():self.fail('RECORD_ACCESS_DENIED')
        return self.record_value(original,self.hierarchy_interface(definition)['current']['columns'])
    def hierarchy_path(self,definitions,start,target):
        path=[]
        for _ in range(20):
            definition=definitions.get(start)
            if definition is None:return None
            path.append(definition)
            if start==target:return path
            start=definition.get('master_register_id')
            if not start:return None
        return None
    def hierarchy_wire(self,c,definition,originals):
        if not originals:return []
        values=[self.record_value(original,self.hierarchy_interface(definition)['current']['columns']) for original in originals]
        ids=[value.get('internal_record_id') for value in values if value.get('internal_record_id')]
        links=list(c.execute(select(documents.c.data).where(documents.c.kind=='section',documents.c.state=='READY',documents.c.data['internal_record_id'].as_string().in_(ids)).order_by(documents.c.position)).scalars()) if ids else []
        document_ids={value.get('record_image_document_id') for value in values if value.get('record_image_document_id')}|{link['document_id'] for link in links}
        catalog={value['document_id']:value for value in c.execute(select(documents.c.data).where(documents.c.kind=='catalog',documents.c.state=='READY',documents.c.id.in_(document_ids))).scalars()} if document_ids else {}
        section_documents={}
        for link in links:
            document=catalog.get(link['document_id'])
            if document:section_documents.setdefault(link['internal_record_id'],[]).append(self.doc_wire(document,link.get('section_id'),link.get('label')))
        for value in values:
            image=value.get('record_image_document_id')
            if image:
                document=catalog.get(image);value['record_image_url']=self.storage.get_url(document['document_store_id'],document['bucket']) if document else None
            value['documents']=section_documents.get(value.get('internal_record_id'),[])
        return [self.models.model('RecordData').model_validate(value).model_dump(mode='json') for value in values]
    def hierarchy_section(self,c,definitions,subject_register,subject,target,policies=()):
        start=self.hierarchy_definition(definitions,subject_register);end=self.hierarchy_definition(definitions,target)
        if subject_register==target:
            self.hierarchy_subject(c,start,subject,policies)
            return self.hierarchy_wire(c,end,list(c.execute(self.hierarchy_query(end).where(records.c.record_id==subject)).scalars()))
        down=self.hierarchy_path(definitions,target,subject_register);up=self.hierarchy_path(definitions,subject_register,target)
        peer=start.get('master_register_id')==end.get('master_register_id')
        if not down and not up and not peer:self.fail('REGISTER_DATA_NOT_FOUND',f'No hierarchy path found between registers {subject_register} and {target}')
        # The old section route did not inject its authoritative policies.
        # Enforce the same subject restriction used by the protected tab route.
        if down or peer:
            value=self.hierarchy_subject(c,start,subject,policies,missing='subject')
        elif policies:self.hierarchy_subject(c,start,subject,policies)
        if down:
            ids=[subject];path=list(reversed(down))[1:]
            for i,definition in enumerate(path):
                self.hierarchy_interface(definition,'link_internal_record_id');query=self.hierarchy_query(definition).where(records.c.link_id.in_(ids))
                if i==len(path)-1:
                    condition=self.record_policy(definition,policies)
                    if condition is not None:query=query.where(condition)
                originals=list(c.execute(query).scalars())
                if not originals:return []
                if i==len(path)-1:return self.hierarchy_wire(c,definition,originals)
                self.hierarchy_interface(definition,'internal_record_id');ids=[self.record_value(original,self.hierarchy_interface(definition)['current']['columns'])['internal_record_id'] for original in originals]
        if up:
            key=subject
            for definition in up[:-1]:
                self.hierarchy_interface(definition,'link_internal_record_id');value=self.hierarchy_subject(c,definition,key)
                key=value.get('link_internal_record_id')
                if not key:return []
            self.hierarchy_interface(end,'internal_record_id');query=self.hierarchy_query(end).where(records.c.record_id==key)
        else:
            self.hierarchy_interface(end,'link_internal_record_id');query=self.hierarchy_query(end).where(records.c.link_id==value.get('link_internal_record_id'))
        condition=self.record_policy(end,policies)
        if condition is not None:query=query.where(condition)
        return self.hierarchy_wire(c,end,list(c.execute(query).scalars()))
    def execute_policy_request(self,path,p,principal,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_policy_request(path,p,principal,pagination)
        if not isinstance(principal,RegistryPrincipal):raise ValueError('Trusted hierarchy principal required')
        policies=principal.data_policies
        with self.engine.connect() as c:
            definitions={value['register_id']:value for value in self.definitions(c)};subject_register=p['subject_register_id'];definition=self.hierarchy_definition(definitions,subject_register)
            if path.endswith('/get_allowed_parents_for_a_child_section'):
                child=self.hierarchy_definition(definitions,p['section_register_id']);parent_id=child.get('master_register_id')
                if not parent_id:self.fail('REGISTER_NOT_FOUND',f"Section register {child['register_id']} has no parent register")
                parent=self.hierarchy_definition(definitions,parent_id)
                try:values=self.hierarchy_section(c,definitions,subject_register,p['internal_record_id'],parent_id,policies)
                except RegistryAuthError:raise
                except Exception:values=[]
                return {'register_mnemonic':parent['register_mnemonic'],'master_register_id':parent.get('master_register_id'),'allowed_parents':[{'internal_record_id':value.get('internal_record_id'),'record_name':value.get('record_name')} for value in values]},None
            subject=p['subject_record_id']
            if path.endswith('/get_section_records'):return self.hierarchy_section(c,definitions,subject_register,subject,p['section_register_id'],policies),None
            self.hierarchy_subject(c,definition,subject,policies)
            sections=[value for value in self.rows(c,'section') if value['register_id']==subject_register];by_id={value['section_id']:value for value in sections}
            links=sorted([value for value in self.rows(c,'link') if value['register_id']==subject_register and value['tab_id']==p['tab_id']],key=lambda value:value['section_order'])
            groups=list(dict.fromkeys((by_id[link['section_id']]['section_register_id'],by_id[link['section_id']]['is_list']) for link in links if link['section_id'] in by_id))
            if not groups:return [],None
            eligible={value['section_id'] for value in sections if value['section_register_id']==subject_register or value['is_list']};ideal=sum(value.get('section_weightage') or 0.0 for value in sections if value['section_id'] in eligible)
            actual=sum(value.get('computed_section_completion_score') or 0.0 for value in c.execute(select(rows.c.data).where(rows.c.kind=='completion',rows.c.register_id==subject_register,rows.c.record_id==subject,rows.c.section_id.in_(eligible))).scalars())
            result=[]
            for target,is_list in groups:
                values=self.hierarchy_section(c,definitions,subject_register,subject,target,policies)
                for value in values:value.update(actual_score=actual,ideal_score=ideal,completion_score_required=bool(definition.get('completion_score_required')))
                result.append({'section_register_id':target,'is_list':is_list,'records':values})
            return result,None
