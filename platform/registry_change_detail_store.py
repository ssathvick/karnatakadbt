"""Own detailed change view, prior versions, image URLs and evidence links."""
import copy
from sqlalchemy import select
from registry_operation_store import RegistryOperationStore
from registry_row_store import rows
from registry_record_store import records,record_timestamp
from registry_layout_store import layouts
from registry_document_store import documents
from registry_metadata_store import RegistryError
from registry_metadata_api import RegistryPrincipal
from registry_data_policy import RecordPolicyCompiler,PolicyConfigurationError

DETAIL_PATH='/change-requests/get_change_request'
SUPPORTED_PATHS=frozenset([DETAIL_PATH])

class RegistryChangeDetailStore(RegistryOperationStore):
    def previous_values(self,c,value,payload,policies):
        definition=self.definition(c,'register',value['section_register_id']);ids=[item['internal_record_id'] for item in payload or [] if item.get('internal_record_id')]
        if definition is None:
            if any(policy.get('register_id')==value['section_register_id'] for policy in policies):raise PolicyConfigurationError()
            return []
        interface=self.record_interface(definition)
        if policies and any(policy.get('register_id')==definition['register_id'] for policy in policies) and (not interface or not interface.get('current')):raise PolicyConfigurationError()
        if not interface:return []
        if policies:
            condition=self.record_policy(definition,policies)
            if condition is not None:
                readable=set(c.execute(select(records.c.record_id).where(records.c.kind=='current',records.c.register_id==definition['register_id'],records.c.record_id.in_(ids),condition)).scalars())
                if any(key not in readable for key in ids):self.fail('RECORD_ACCESS_DENIED')
        approved=value['approval_status']=='APPROVED';kind='history' if approved else 'current';meta=interface.get(kind)
        if not meta:return []
        query=select(records.c.record_id,records.c.source_json).where(records.c.kind==kind,records.c.register_id==definition['register_id'],records.c.record_id.in_(ids))
        if approved:
            if not value.get('approved_at'):return []
            query=query.where(records.c.approved_at<record_timestamp(value['approved_at'])).distinct(records.c.record_id).order_by(records.c.record_id,records.c.approved_at.desc())
        originals=c.execute(query).all();values={key:self.record_value(original,meta['columns']) for key,original in originals};result=[]
        for key in ids if approved else values:
            if key not in values:continue
            record=dict(values[key])
            if approved:
                approved_by=record.get('approved_by');approved_at=record.get('approved_at')
                for field in ['history_record_id','change_request_id','tab_id','section_id','submission_id','change_request_source','is_primary_section','approved_by','approved_at','search_text']:record.pop(field,None)
                record.update(last_approved_by=approved_by,last_approved_at=approved_at)
            else:record.pop('search_text',None)
            result.append(record)
        return result
    def change_documents(self,c,key):
        links=list(c.execute(select(documents.c.data).where(documents.c.kind=='change',documents.c.state=='READY',documents.c.data['change_request_id'].as_string()==key).order_by(documents.c.position)).scalars());ids=[value['document_id'] for value in links];catalog={value['document_id']:value for value in c.execute(select(documents.c.data).where(documents.c.kind=='catalog',documents.c.state=='READY',documents.c.id.in_(ids))).scalars()} if ids else {}
        return [self.doc_wire(catalog[value['document_id']],value.get('section_id'),value.get('label')) for value in links if value['document_id'] in catalog]
    def execute_policy_request(self,path,p,principal,pagination=None):
        if path!=DETAIL_PATH:return super().execute_policy_request(path,p,principal,pagination)
        if not isinstance(principal,RegistryPrincipal):raise ValueError('Trusted change-detail principal required')
        with self.engine.begin() as c:
            value=c.execute(select(rows.c.data).where(rows.c.kind=='change',rows.c.key==self.row_key('change',{'change_request_id':p['change_request_id']})).with_for_update()).scalar_one_or_none()
            if value is None:self.fail('CHANGE_REQUEST_NOT_FOUND')
            value=dict(value);self.require_readable_subject(c,value['register_id'],value['internal_record_id'],principal.data_policies)
            body=c.execute(select(rows.c.data).where(rows.c.kind=='change-payload',rows.c.key==self.row_key('change-payload',{'change_request_id':value['change_request_id']}))).scalar_one_or_none()
            if body is None:self.fail('CHANGE_REQUEST_NOT_FOUND')
            payload=copy.deepcopy(body.get('change_payload'))
            if payload and (not isinstance(payload,list) or any(not isinstance(item,dict) for item in payload)):raise RegistryError('SYS-ERR-001')
            value=self.reconcile_summary(c,'change',value);previous=self.previous_values(c,value,payload,principal.data_policies)
            section=c.execute(select(layouts.c.data).where(layouts.c.kind=='section',layouts.c.id==value['section_id'])).scalar_one_or_none()
            if section is None:raise RegistryError('SYS-ERR-001')
            definition=self.definition(c,'register',value['register_id']);tab=c.execute(select(layouts.c.data).where(layouts.c.kind=='tab',layouts.c.id==value['tab_id'])).scalar_one_or_none()
            all_records=[*(payload or []),*previous];ids={record.get('record_image_document_id') for record in all_records if record.get('record_image_document_id')};catalog=list(c.execute(select(documents.c.data).where(documents.c.kind=='catalog',documents.c.state=='READY',documents.c.id.in_(ids))).scalars()) if ids else [];urls={record['document_id']:self.storage.get_url(record['document_store_id'],record['bucket']) for record in catalog}
            for record in all_records:
                if record.get('record_image_document_id'):record['record_image_url']=urls.get(record['record_image_document_id'])
            item={field:value.get(field) for field in self.models.definitions['ChangeRequestData']['properties']};item.update(register_mnemonic=definition.get('register_mnemonic') if definition else None,tab_label=tab.get('tab_label') if tab else None,section_mnemonic=section['section_mnemonic'],is_list=section['is_list'],change_payload=payload,current_register_data=previous,documents=self.change_documents(c,value['change_request_id']))
            for field in ['created_at','approved_at']:item[field]=record_timestamp(value[field]).isoformat() if value.get(field) else None
            return self.models.model('ChangeRequestData').model_validate(item).model_dump(mode='json'),None
