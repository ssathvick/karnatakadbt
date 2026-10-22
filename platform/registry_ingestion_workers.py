"""Native incoming classification and template transformation jobs."""
import copy,json,re
from jsonpath_ng import parse
from sqlalchemy import select,insert,update
from registry_native_workers import WorkerFailure
from registry_outgoing_workers import render_outgoing
from registry_message_data_store import messages
from registry_message_template_store import templates
from registry_ingestion_config_store import patterns
from registry_document_store import documents
from registry_layout_store import layouts
from registry_record_store import records

TASKS=frozenset({'ingest_data_classification_worker','ingest_data_transformation_worker'})
def extract(data,path):
    matches=parse(path).find(data)
    return matches[0].value if matches else None
def pattern_matches(data,pattern):
    if not isinstance(pattern,str) or '=>' not in pattern:raise WorkerFailure('INGEST_PATTERN_INVALID')
    path,expression=pattern.split('=>',1);value=extract(data,path)
    return value if value is not None and re.fullmatch(expression,str(value)) else None
def business_payload(data,path):
    matches=parse(path).find(data)
    if not matches:return None
    if len(matches)>1:return {match.path.fields[0]:match.value for match in matches}
    value=matches[0].value
    if isinstance(value,str):return json.loads(value.strip()) if value.strip() else None
    if isinstance(value,dict):return value
    raise WorkerFailure('INGEST_BUSINESS_PAYLOAD_TYPE_INVALID')

class NativeIngestionWorkers:
    def __init__(self,store,max_attempts=5,jsonld_loader=None):
        if not isinstance(max_attempts,int) or max_attempts<1:raise ValueError('Positive attempt limit required')
        self.store,self.max_attempts,self.jsonld_loader=store,max_attempts,jsonld_loader
    def run(self,task,key):
        if task not in TASKS:raise ValueError('Unimplemented incoming worker')
        kind='incoming' if task=='ingest_data_classification_worker' else 'classified';prefix='classification' if kind=='incoming' else 'transformation'
        with self.store.engine.begin() as c:
            value=c.execute(select(messages.c.data).where(messages.c.kind==kind,messages.c.key==key).with_for_update()).scalar_one_or_none()
            if value is None:return {'status':'NOT_FOUND'}
            value=copy.deepcopy(value)
            if value.get(prefix+'_status')!='PENDING':return {'status':value.get(prefix+'_status'),'skipped':True}
            if (value.get(prefix+'_number_of_attempts') or 0)>=self.max_attempts:value[prefix+'_status']='FAILED'
            else:
                try:
                    with c.begin_nested():
                        raw=self.store.message(c,'incoming-payload',key)
                        if raw is None:raise WorkerFailure('INGEST_RAW_PAYLOAD_MISSING')
                        if kind=='incoming':self._classify(c,value,raw['raw_data_json'])
                        else:self._transform(c,value,raw['raw_data_json'])
                    value[prefix+'_status']='PROCESSED';value[prefix+'_latest_error_code']=None
                except Exception as failure:
                    value[prefix+'_status']='FAILED' if (value.get(prefix+'_number_of_attempts') or 0)+1>=self.max_attempts else 'PENDING'
                    value[prefix+'_latest_error_code']=str(failure) if isinstance(failure,WorkerFailure) else 'INGEST_WORKER_FAILED'
                value[prefix+'_number_of_attempts']=(value.get(prefix+'_number_of_attempts') or 0)+1
                value[prefix+'_date_time']=self.store.clock().replace(tzinfo=None).isoformat()
            c.execute(update(messages).where(messages.c.kind==kind,messages.c.key==key).values(data=value))
            return {'status':value[prefix+'_status'],'attempts':value.get(prefix+'_number_of_attempts',0),'error':value.get(prefix+'_latest_error_code')}
    def _identity(self,c,register,identifier):
        definition=self.store.definition(c,'register',register)
        if definition is None:return None
        profile=self.store.record_interface(definition)
        if not profile or not profile.get('current'):raise WorkerFailure('INGEST_REGISTER_INTERFACE_MISSING')
        for field in ['functional_record_id','foundational_id']:
            if field not in profile['current']['columns']:continue
            values=list(c.execute(select(records.c.data).where(records.c.kind=='current',records.c.register_id==register,records.c.data[field].astext==identifier)).scalars())
            if len(values)>1:raise WorkerFailure('INGEST_IDENTIFIER_NOT_UNIQUE')
            if values:
                if not values[0].get('internal_record_id'):raise WorkerFailure('INGEST_RECORD_STATE_INVALID')
                return values[0]['internal_record_id']
        return None
    def _classify(self,c,value,data):
        registers=[item for item in self.store.incoming_rows(c,'register') if item['data_model_id']==value['data_model_id']]
        semantics=[item for item in self.store.incoming_rows(c,'semantic') if item['data_model_id']==value['data_model_id']]
        action='ADD';record=None;register=None;matched=None
        if registers:
            register_pattern=next((item for item in registers if pattern_matches(data,item['pattern_for_register'])),None)
            if register_pattern is None:raise WorkerFailure('REGISTER_PATTERN_NOT_MATCHED')
            raw=extract(data,register_pattern['key_path_for_record_identifier']);identifier=str(raw).strip() if raw is not None else ''
            if not identifier:raise WorkerFailure('RECORD_IDENTIFIER_EMPTY')
            register=register_pattern['register_id'];record=self._identity(c,register,identifier);action='UPDATE' if record else 'ADD'
            for item in semantics:
                if item['register_id']!=register:continue
                pattern=item.get('pattern_for_section') if action=='UPDATE' else item.get('pattern_for_intake_form')
                if action=='UPDATE' and not item.get('section_id'):continue
                if pattern and pattern_matches(data,pattern):matched=item;break
        else:
            for item in semantics:
                if item.get('pattern_for_register') and not pattern_matches(data,item['pattern_for_register']):continue
                if pattern_matches(data,item['pattern_for_intake_form']):matched=item;register=item['register_id'];break
        if matched is None or action=='ADD' and not matched.get('intake_form_id'):raise WorkerFailure('SECTION_PATTERN_NOT_MATCHED' if action=='UPDATE' else 'INTAKE_FORM_PATTERN_NOT_MATCHED')
        result=self.store.ingest_defaults('classified');result.update(ingest_id=value['ingest_id'],partner_id=value['partner_id'],data_model_id=value['data_model_id'],register_id=register,pipeline_action=action,
            section_id=matched.get('section_id') if action=='UPDATE' else None,internal_record_id=record,intake_form_id=matched.get('intake_form_id') if action=='ADD' else None,
            semantic_pattern_id=matched['semantic_pattern_id'],classified_date_time=self.store.clock().replace(tzinfo=None).isoformat())
        self.store.validate_ingest_row('classified',result)
        c.execute(insert(messages).values(kind='classified',key=result['ingest_id'],data=result))
    def _enrich(self,c,name,data):
        data=copy.deepcopy(data)
        if name=='G2PDciIndividualCreateEnricherService':
            if isinstance(data,dict):
                raw=data.get('additional_attributes');merged={}
                for item in [raw] if isinstance(raw,dict) else raw if isinstance(raw,list) else []:
                    if isinstance(item,dict):merged.update(item)
                data['additional_attributes']=merged
            return data
        if name=='G2PCrvsVCIndividualCreateEnricherService':
            if not isinstance(data,dict):return data
            envelope=data['vc'] if isinstance(data.get('vc'),dict) else data
            parents=((envelope.get('jwt') or {}).get('payload') or {}).get('parents')
            parents=[parents] if isinstance(parents,dict) else parents if isinstance(parents,list) else []
            definition=next((value for value in self.store.definitions(c) if value['register_mnemonic']=='Individual'),None)
            if definition:
                for parent in parents:
                    if not isinstance(parent,dict) or not parent.get('identifier'):continue
                    values=list(c.execute(select(records.c.data).where(records.c.kind=='current',records.c.register_id==definition['register_id'],records.c.data['foundational_id'].astext==str(parent['identifier']))).scalars())
                    if len(values)>1:raise WorkerFailure('CRVS_PARENT_IDENTITY_NOT_UNIQUE')
                    if values and values[0].get('link_internal_record_id'):return {**envelope,'link_internal_record_id':values[0]['link_internal_record_id']}
            raise WorkerFailure('CRVS_PARENT_LINK_NOT_FOUND')
        if name in {f'G2P{protocol}{subject}{action}EnricherService' for protocol in ['Dci','Spdci','Undp'] for subject in ['Household','Individual'] for action in ['Create','Update','Delete']}:return data
        raise WorkerFailure('PAYLOAD_ENRICHER_UNSUPPORTED')
    def _transform(self,c,value,data):
        semantic=next((item for item in self.store.incoming_rows(c,'semantic') if item['semantic_pattern_id']==value['semantic_pattern_id']),None)
        if semantic is None:raise WorkerFailure('INGEST_SEMANTIC_PATTERN_MISSING')
        payload=business_payload(data,semantic['key_path_for_business_payload'])
        if not payload:raise WorkerFailure('INGEST_BUSINESS_PAYLOAD_MISSING')
        enriched=self._enrich(c,semantic.get('raw_payload_enricher_class'),payload);register=value['register_id']
        if (value.get('pipeline_action') or 'ADD')=='ADD':
            form=self.store.definition(c,'form',value.get('intake_form_id'))
            if form:register=form['register_id']
        matching=[item for item in self.store.template_rows(c,'incoming') if item['data_model_id']==value['data_model_id'] and item['register_id']==register]
        if len(matching)!=1:raise WorkerFailure('INGEST_TEMPLATE_NOT_UNIQUE')
        template=matching[0];document=c.execute(select(documents.c.data).where(documents.c.kind=='catalog',documents.c.id==template['template_document_id'],documents.c.state=='READY')).scalar_one_or_none()
        if not document:raise WorkerFailure('INGEST_TEMPLATE_DOCUMENT_MISSING')
        expanded=enriched
        if template.get('jsonld_expansion_required'):
            from pyld import jsonld
            def deny_remote(url,options=None):raise WorkerFailure('JSONLD_REMOTE_CONTEXT_NOT_ALLOWED')
            expanded=jsonld.expand(enriched,options={'documentLoader':self.jsonld_loader or deny_remote})
        transformed=render_outgoing(self.store.storage.get_bytes(document['document_store_id'],document['bucket']).decode(),expanded)
        if not isinstance(transformed,dict) or not transformed:raise WorkerFailure('INGEST_TRANSFORMED_PAYLOAD_INVALID')
        if (value.get('pipeline_action') or 'ADD')=='UPDATE':
            section=next((item for item in self.store.rows(c,'section') if item['section_id']==value.get('section_id')),None)
            if not section or section['section_mnemonic'] not in transformed or transformed[section['section_mnemonic']] is None or transformed[section['section_mnemonic']]==[]:raise WorkerFailure('SECTION_DATA_MISSING_IN_TRANSFORMED_PAYLOAD')
        else:
            if not value.get('intake_form_id'):raise WorkerFailure('INTAKE_FORM_REQUIRED_FOR_ADD_TRANSFORMATION')
            sections=self.store.submission_sections(c,value['intake_form_id'])
            if not sections or not any(section['section_mnemonic'] in transformed and section['section_register_id']==value['register_id'] for section,_ in sections):raise WorkerFailure('INGEST_SUBJECT_SECTION_MISSING')
        output={field:None for field in self.store.message_contract()['enriched']['columns']};output.update(ingest_id=value['ingest_id'],enriched_data_json=enriched,transformed_data_json=transformed)
        c.execute(insert(messages).values(kind='enriched',key=value['ingest_id'],data=output));value['ingestion_status']='PENDING'
