"""Policy-aware history and register counts over the own record store."""
import json
from decimal import Decimal
from sqlalchemy import select,func
from registry_record_store import RegistryRecordStore,records,record_timestamp
from registry_document_store import documents
from registry_metadata_api import RegistryPrincipal
from registry_metadata_store import RegistryError
from registry_data_policy import RecordPolicyCompiler,POLICY_PATHS

SUPPORTED_PATHS=frozenset(['/register-data/get_record_history','/register-data/get_register_summary_data','/register-data/get_subject_record'])

class RegistryReadableStore(RegistryRecordStore):
    def record_value(self,original,columns):
        value=json.loads(original,parse_float=Decimal)
        for field,meta in columns.items():
            if meta['type'].startswith('timestamp') and value.get(field):value[field]=record_timestamp(value[field]).isoformat()
            if meta['type'] in {'double precision','real'} and isinstance(value.get(field),Decimal):value[field]=float(value[field])
            if meta['type'] in {'json','jsonb'} and value.get(field) is not None:value[field]=json.loads(json.dumps(value[field],default=lambda item:float(item) if isinstance(item,Decimal) else item))
        return value
    def record_policy(self,definition,policies):
        interface=self.record_interface(definition)
        if not interface or not interface.get('current'):return None
        return RecordPolicyCompiler(records,interface['current']['columns']).resolve(policies,definition['register_id'])
    def execute_policy_request(self,path,p,principal,pagination=None):
        if path not in SUPPORTED_PATHS or not isinstance(principal,RegistryPrincipal):raise ValueError('A trusted authenticated record principal is required')
        with self.engine.connect() as c:
            if path.endswith('/get_register_summary_data'):
                output=[]
                for definition in self.definitions(c):
                    if definition['register_purpose']!='REGISTER':continue
                    interface=self.record_interface(definition);total=0
                    if interface and interface['extension_current_available']:
                        query=select(func.count()).select_from(records).where(records.c.kind=='current',records.c.register_id==definition['register_id'],records.c.data['record_status'].astext=='ACTIVE')
                        condition=self.record_policy(definition,principal.data_policies)
                        if condition is not None:query=query.where(condition)
                        total=c.execute(query).scalar_one()
                    output.append({**{field:definition.get(field) for field in ['register_id','register_mnemonic','register_subject','has_image','register_icon']},'total_record_count':total})
                return output,None
            subject_read=path.endswith('/get_subject_record');register=p['subject_register_id'] if subject_read else p['register_id'];record=p['subject_record_id'] if subject_read else p['internal_record_id'];definition=self.require_definition(c,register);interface=self.record_interface(definition)
            if not interface or not interface['extension_current_available']:self.fail('REGISTER_DATA_NOT_FOUND')
            query=select(records.c.source_json).where(records.c.kind=='current',records.c.register_id==register,records.c.record_id==record)
            condition=self.record_policy(definition,principal.data_policies)
            original=c.execute(query if condition is None else query.where(condition)).scalar_one_or_none()
            if original is None:
                if condition is not None and c.execute(query).first():self.fail('RECORD_ACCESS_DENIED')
                self.fail('REGISTER_DATA_NOT_FOUND')
            if subject_read:
                value=self.record_value(original,interface['current']['columns'])
                image=value.get('record_image_document_id')
                if image:
                    document=c.execute(select(documents.c.data).where(documents.c.kind=='catalog',documents.c.state=='READY',documents.c.id==image)).scalar_one_or_none()
                    value['record_image_url']=self.storage.get_url(document['document_store_id'],document['bucket']) if document else None
                links=list(c.execute(select(documents.c.data).where(documents.c.kind=='section',documents.c.state=='READY',documents.c.data['internal_record_id'].as_string()==record).order_by(documents.c.position)).scalars())
                catalog={item['document_id']:item for item in c.execute(select(documents.c.data).where(documents.c.kind=='catalog',documents.c.state=='READY',documents.c.id.in_([link['document_id'] for link in links]))).scalars()} if links else {}
                value['documents']=[self.doc_wire(catalog[link['document_id']],link.get('section_id'),link.get('label')) for link in links if link['document_id'] in catalog]
                return self.models.model('RecordData').model_validate(value).model_dump(mode='json'),None
            history=[]
            # The existing history endpoint returns this record's full history,
            # irrespective of the echoed tab identifier. Match that contract.
            for original in c.execute(select(records.c.source_json).where(records.c.kind=='history',records.c.register_id==register,records.c.record_id==record).order_by(records.c.approved_at.desc())).scalars():
                value=self.record_value(original,interface['history']['columns']);value.pop('subject_internal_record_id',None)
                history.append(self.models.model('RecordHistoryData').model_validate(value).model_dump(mode='json'))
            return {'register_id':register,'internal_record_id':p['internal_record_id'],'tab_id':p['tab_id'],'history_records':history},None
