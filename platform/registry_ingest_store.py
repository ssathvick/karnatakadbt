"""Own incoming envelope admission and classification queue writes."""
import copy,datetime,json,re,uuid
from pathlib import Path
from functools import cached_property
from jsonpath_ng import parse
from sqlalchemy import select,insert,MetaData,Table,Column,String,DateTime,Index
from sqlalchemy.dialects.postgresql import JSONB
from registry_intake_write_store import RegistryIntakeWriteStore
from registry_configuration_store import catalog
from registry_ingestion_config_store import patterns
from registry_message_data_store import messages
from registry_document_store import documents
from registry_metadata_api import RegistryPrincipal,RegistryAuthError
from registry_metadata_store import RegistryError
INGEST_PATH='/input-mechanism-data/ingest-data'
SUPPORTED_PATHS=frozenset([INGEST_PATH])
Index('ix_console_incoming_pending_time',messages.c.kind,messages.c.data['classification_status'].astext,messages.c.data['receipt_date_time'].astext)
Index('ix_console_classified_pending_time',messages.c.kind,messages.c.data['transformation_status'].astext,messages.c.data['classified_date_time'].astext)
metadata=MetaData()
ingest_context=Table('console_registry_ingest_context',metadata,Column('correlation_id',String,primary_key=True),Column('actor',String,nullable=False),Column('policies',JSONB,nullable=False),Column('policy_mnemonics',JSONB,nullable=False),Column('queued_at',DateTime,nullable=False))
class RegistryIngestStore(RegistryIntakeWriteStore):
    def __init__(self,*args,partner_client=None,ingest_uuid_factory=None,**kwargs):super().__init__(*args,**kwargs);self.partner_client=partner_client;self.ingest_uuid_factory=ingest_uuid_factory or uuid.uuid4
    def initialize(self):super().initialize();metadata.create_all(self.engine)
    @cached_property
    def ingest_contract(self):return json.loads(Path(__file__).with_name('registry_ingest_contract.json').read_text())
    def ingest_defaults(self,kind):
        value={k:None for k in self.message_contract()[kind]['columns']};value.update({k:v['default'] for k,v in self.ingest_contract['models'][kind]['fields'].items() if 'default' in v});return value
    def validate_ingest_row(self,kind,value):
        for field,column in self.message_contract()[kind]['columns'].items():
            if not column['nullable'] and value.get(field) is None:raise RegistryError('SYS-ERR-001')
    def admit_ingest(self,body,headers,query,principal):
        if not isinstance(principal,RegistryPrincipal):raise ValueError('Verified ingest principal required')
        envelope={'headers':dict(headers),'body':body}
        def extract(path):
            matches=parse(path).find(envelope);return matches[0].value if matches else None
        with self.engine.begin() as c:
            mnemonic=query.get('data_model');mnemonic=mnemonic.upper() if mnemonic else None
            models=list(c.execute(select(catalog.c.data).where(catalog.c.kind=='model').order_by(catalog.c.position)).scalars())
            if not mnemonic:
                # Preserve the captured service's iteration semantics. The
                # final model's pattern result is the model selector.
                for model in models:
                    path,regex=model['pattern_for_data_model'].split('=>',1);value=extract(path);mnemonic=value if value is not None and re.fullmatch(regex,str(value)) else None
            matching=[m for m in models if m['data_model_mnemonic']==mnemonic]
            if len(matching)>1:raise RegistryError('SYS-ERR-001')
            if not matching:self.fail('DATA_MODEL_NOT_FOUND')
            model=matching[0];keys=list(c.execute(select(patterns.c.data).where(patterns.c.kind=='key',patterns.c.data['data_model_id'].as_string()==model['data_model_id'])).scalars())
            if len(keys)>1:raise RegistryError('SYS-ERR-001')
            if not keys:self.fail('INVALID_REQUEST',f"No incoming_model_key_paths row for data_model_id={model['data_model_id']}; configure key paths for this model")
            key=keys[0];sender=extract(key['key_path_for_sender']);signature=extract(key['key_path_for_signature']);signed_payload=extract(key['key_path_for_signature_payload']);missing=[]
            for value,label,field in [(sender,'sender/partner key','key_path_for_sender'),(signature,'signature key','key_path_for_signature'),(signed_payload,'signature payload key','key_path_for_signature_payload')]:
                if not value:missing.append(f'{label} (path {key[field]!r})')
            if missing:self.fail('INVALID_REQUEST','Ingest envelope missing required JSONPath values for partner routing: '+'; '.join(missing))
            if self.partner_client is None:raise RegistryAuthError(503,'Partner verification service is not configured')
            partner=self.partner_client.require_active(sender);message_id=extract(key['key_path_for_message_id']);payloads=[envelope]
            if key['is_list']:
                expression=parse(key['key_path_for_list_elements']);elements=extract(key['key_path_for_list_elements'])
                if not isinstance(elements,list) or not elements:self.fail('INVALID_REQUEST')
                payloads=[]
                for element in elements:
                    value=copy.deepcopy(envelope);expression.update(value,[element]);payloads.append(value)
            correlation=self.ingest_uuid_factory().hex;register=query.get('register_id');form=query.get('intake_form_id');classified=bool(register and form)
            for payload in payloads:
                ingest=str(self.ingest_uuid_factory());value=self.ingest_defaults('incoming');value.update(ingest_id=ingest,partner_id=partner['partner_id'],data_model_id=model['data_model_id'],ingest_message_id=message_id,ingest_correlation_id=correlation,receipt_date_time=self.clock().isoformat());raw=self.ingest_defaults('incoming-payload');raw.update(ingest_id=ingest,raw_data_json=payload)
                # Console session credentials must not be stored with a
                # beneficiary payload; envelope signature headers remain.
                raw['raw_data_json']={**payload,'headers':{k:v for k,v in payload['headers'].items() if k.lower() not in {'authorization','cookie','proxy-authorization','x-access-token','x-refresh-token','x-csrf-token'}}}
                raw['raw_data_text']=json.dumps(raw['raw_data_json'])
                if classified:
                    value.update(classification_status='PROCESSED',classification_date_time=self.clock().isoformat());matches=list(c.execute(select(patterns.c.data).where(patterns.c.kind=='semantic',patterns.c.data['register_id'].as_string()==register,patterns.c.data['intake_form_id'].as_string()==form,patterns.c.data['data_model_id'].as_string()==model['data_model_id'])).scalars())
                    if len(matches)>1:raise RegistryError('SYS-ERR-001')
                    if not matches:self.fail('INVALID_REQUEST',f"No incoming_model_semantic_patterns row for register_id={register}, intake_form_id={form}, data_model_id={model['data_model_id']}")
                    classified_value=self.ingest_defaults('classified');classified_value.update(ingest_id=ingest,data_model_id=model['data_model_id'],partner_id=partner['partner_id'],register_id=register,intake_form_id=form,semantic_pattern_id=matches[0]['semantic_pattern_id'],classified_date_time=self.clock().isoformat(),transformation_status='PENDING');self.validate_ingest_row('classified',classified_value);c.execute(insert(messages).values(kind='classified',key=ingest,data=classified_value))
                for kind,item in [('incoming',value),('incoming-payload',raw)]:
                    self.validate_ingest_row(kind,item)
                    for field,meta in self.ingest_contract['models'][kind]['fields'].items():
                        if meta.get('max_length') and item.get(field) is not None and len(item[field])>meta['max_length']:raise RegistryError('SYS-ERR-001')
                    if kind=='incoming' and message_id is not None and not isinstance(message_id,str):raise RegistryError('SYS-ERR-001')
                    c.execute(insert(messages).values(kind=kind,key=ingest,data=item))
            stamp=datetime.datetime.fromisoformat(value['receipt_date_time']);document=model.get('response_template_document_id')
            if document:
                value=c.execute(select(documents.c.data).where(documents.c.kind=='catalog',documents.c.id==document,documents.c.state=='READY')).scalar_one_or_none()
                if value is None or value['bucket']!='templates':self.fail('TEMPLATE_NOT_FOUND','TEMPLATE_NOT_FOUND: document_id='+document)
            c.execute(insert(ingest_context).values(correlation_id=correlation,actor=principal.subject,policies=list(principal.data_policies),policy_mnemonics=list(principal.policy_mnemonics),queued_at=stamp));self.record_decision(c,INGEST_PATH,correlation,principal,stamp=stamp)
            return {'correlation_id':correlation}
