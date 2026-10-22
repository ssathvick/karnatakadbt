"""Policy-aware change-request list and dashboard over own captured state."""
from sqlalchemy import select,func,or_,and_,exists
from registry_change_query_store import RegistryChangeQueryStore
from registry_row_store import rows
from registry_record_store import records,record_timestamp
from registry_layout_store import layouts
from registry_metadata_api import RegistryPrincipal
from registry_metadata_store import RegistryError

SUPPORTED_PATHS=frozenset(['/change-requests/get_change_requests','/change-requests/get_register_change_request_summary_data'])

class RegistryChangePolicyStore(RegistryChangeQueryStore):
    def change_search_policy(self,c,policies):
        if not policies:return None
        clauses=[]
        for definition in self.definitions(c):
            interface=self.record_interface(definition)
            if not interface or not interface['extension_current_available']:continue
            condition=self.record_policy(definition,policies)
            clause=rows.c.register_id==definition['register_id']
            if condition is not None:
                readable=select(1).select_from(records).where(records.c.kind=='current',records.c.register_id==definition['register_id'],records.c.record_id==rows.c.record_id,condition)
                clause=and_(clause,exists(readable))
            clauses.append(clause)
        return or_(*clauses) if clauses else None
    def require_readable_subject(self,c,register,key,policies):
        definition=self.require_definition(c,register);interface=self.record_interface(definition)
        if not interface or not interface['extension_current_available']:raise RegistryError('SYS-ERR-001')
        query=select(records.c.key).where(records.c.kind=='current',records.c.register_id==register,records.c.record_id==key)
        condition=self.record_policy(definition,policies)
        if c.execute(query if condition is None else query.where(condition)).first():return
        if condition is not None and c.execute(query).first():self.fail('RECORD_ACCESS_DENIED')
        self.fail('REGISTER_DATA_NOT_FOUND')
    def execute_policy_request(self,path,p,principal,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_policy_request(path,p,principal,pagination)
        if not isinstance(principal,RegistryPrincipal):raise ValueError('A trusted authenticated record principal is required')
        with self.engine.connect() as c:
            if path.endswith('/get_register_change_request_summary_data'):
                query=select(rows.c.status,func.count()).where(rows.c.kind=='change')
                condition=self.change_search_policy(c,principal.data_policies)
                if condition is not None:query=query.where(condition)
                counts=dict(c.execute(query.group_by(rows.c.status)).all())
                return {'total_count':sum(counts.values()),'approved_count':counts.get('APPROVED',0),'pending_count':counts.get('PENDING',0)},None
            if pagination is None:raise RegistryError('SYS-ERR-001')
            self.require_readable_subject(c,p['subject_register_id'],p['subject_record_id'],principal.data_policies)
            condition=and_(rows.c.kind=='change',rows.c.register_id==p['subject_register_id'],rows.c.record_id==p['subject_record_id'],rows.c.data['tab_id'].astext==p['tab_id'])
            total=c.execute(select(func.count()).select_from(rows).where(condition)).scalar_one()
            payload=rows.alias('flattened_payload')
            query=select(rows.c.data,payload.c.data).select_from(rows.join(payload,(payload.c.kind=='change-payload') & (rows.c.data['change_request_id'].astext==payload.c.data['change_request_id'].astext))).where(condition).order_by(rows.c.at.desc()).offset((pagination['current_page']-1)*pagination['page_size']).limit(pagination['page_size'])
            values=c.execute(query).all();sections={value['section_id']:value for value in self.rows(c,'section')};definition=self.definition(c,'register',p['subject_register_id']);tab=c.execute(select(layouts.c.data).where(layouts.c.kind=='tab',layouts.c.id==p['tab_id'])).scalar_one_or_none()
            result=[]
            for value,body in values:
                section=sections.get(value['section_id'])
                if section is None:raise RegistryError('SYS-ERR-001')
                item={name:value.get(name) for name in self.models.definitions['ChangeRequestFlattenedData']['properties']}
                item['section_mnemonic']=section['section_mnemonic']
                for name in ['created_at','approved_at']:item[name]=record_timestamp(value[name]).isoformat() if value.get(name) else None
                if isinstance(body.get('change_payload'),dict):item.update({key:val for key,val in body['change_payload'].items() if key!='internal_record_id'})
                item['register_mnemonic']=definition.get('register_mnemonic') if definition else None;item['tab_label']=tab.get('tab_label') if tab else None
                result.append(self.models.model('ChangeRequestFlattenedData').model_validate(item).model_dump(mode='json'))
            return result,{'number_of_items':total,'number_of_pages':(total+pagination['page_size']-1)//pagination['page_size']}
