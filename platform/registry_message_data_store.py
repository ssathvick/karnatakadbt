"""Own indexed message inspection store; no external message delivery."""
import json
from pathlib import Path
from sqlalchemy import MetaData,Table,Column,String,Index,select,insert,func,cast,Integer,DateTime,Boolean
from sqlalchemy.dialects.postgresql import JSONB
from registry_verification_store import RegistryVerificationStore
from registry_configuration_store import catalog
from registry_layout_store import layouts
from registry_message_template_store import templates
from registry_metadata_store import RegistryError

metadata=MetaData()
messages=Table('console_message_data',metadata,Column('kind',String,primary_key=True),Column('key',String,primary_key=True),Column('data',JSONB,nullable=False))
for field in ['data_model_id','partner_id','topic_id','payload_id','receipt_date_time','created_at']:
    Index('ix_console_message_'+field,messages.c.kind,messages.c.data[field].astext)
SUPPORTED_PATHS=frozenset(['/ingestion-data/'+name for name in ['get_ingestion_summary_data','search_in_ingestion_data','get_raw_payload','get_enriched_and_transformed_payload']]+['/outgestion-data/'+name for name in ['get_outgestion_summary_data','search_in_outgestion_data']])

class RegistryMessageDataStore(RegistryVerificationStore):
    def initialize(self):
        super().initialize();metadata.create_all(self.engine)
        for index in messages.indexes:index.create(self.engine,checkfirst=True)
    def message_contract(self):return json.loads(Path(__file__).with_name('registry_message_data_contract.json').read_text())
    def message_rows(self,c,kind):return list(c.execute(select(messages.c.data).where(messages.c.kind==kind).order_by(messages.c.key)).scalars())
    def seed_messages(self,dataset):
        contract=self.message_contract()
        with self.engine.begin() as c:
            for kind,values in dataset.items():
                if c.execute(select(messages.c.key).where(messages.c.kind==kind).limit(1)).first():raise RuntimeError('Refusing to overwrite '+kind)
                for value in values:c.execute(insert(messages).values(kind=kind,key=value[contract[kind]['primary_key']],data=value))
    def message(self,c,kind,key):return c.execute(select(messages.c.data).where(messages.c.kind==kind,messages.c.key==key)).scalar_one_or_none()
    def message_field(self,alias,kind,field):
        typ=self.message_contract()[kind]['columns'][field]['type'];value=alias.c.data[field].astext
        if typ in {'integer','bigint','smallint'}:return cast(value,Integer)
        if typ.startswith('timestamp'):return cast(value,DateTime)
        if typ=='boolean':return cast(value,Boolean)
        if typ=='json':raise RegistryError('SYS-ERR-001')  # PostgreSQL JSON has no ordering operator.
        if typ=='jsonb':return func.nullif(alias.c.data[field],cast('null',JSONB))
        return value
    def page_context(self,c,kind,values):
        context={'classified':{},'catalog':{},'sections':{},'templates':{},'topics':{}}
        if not values:return context
        if kind=='incoming':
            context['classified']={row['ingest_id']:row for row in c.execute(select(messages.c.data).where(messages.c.kind=='classified',messages.c.key.in_([value['ingest_id'] for value in values]))).scalars()}
        classified=list(context['classified'].values());all_values=values+classified
        identifiers={value.get(field) for value in all_values for field in ['data_model_id','register_id','intake_form_id'] if value.get(field)}
        for entry_kind,key,value in c.execute(select(catalog.c.kind,catalog.c.id,catalog.c.data).where(catalog.c.kind.in_(['model','register','form']),catalog.c.id.in_(identifiers))):context['catalog'][entry_kind,key]=value
        if kind=='incoming':
            sections={value['section_id'] for value in classified if value.get('section_id')}
            context['sections']={value['section_id']:value for value in c.execute(select(layouts.c.data).where(layouts.c.kind=='section',layouts.c.id.in_(sections))).scalars()}
            models={value['data_model_id'] for value in values};registers={value['register_id'] for value in classified if value.get('register_id')}
            for value in c.execute(select(templates.c.data).where(templates.c.kind=='incoming',templates.c.data['data_model_id'].as_string().in_(models),templates.c.data['register_id'].as_string().in_(registers)).order_by(templates.c.position)).scalars():context['templates'][value['data_model_id'],value['register_id']]=value
        else:
            keys={value['topic_id'] for value in values}
            context['topics']={value['topic_id']:value for value in c.execute(select(messages.c.data).where(messages.c.kind=='topic',messages.c.key.in_(keys))).scalars()}
        return context
    def incoming_wire(self,value,context):
        classified=context['classified'].get(value['ingest_id'],{})
        output={**value,**{key:item for key,item in classified.items() if key not in {'data_model_id','partner_id','ingest_id'}}}
        output['partner_mnemonic']=value['partner_id']
        for kind,key,name in [('model','data_model_id','data_model_mnemonic'),('register','register_id','register_mnemonic'),('form','intake_form_id','intake_form_mnemonic')]:
            linked=context['catalog'].get((kind,output.get(key)));output[name]=linked.get('form_mnemonic' if kind=='form' else name) if linked else None
        section=context['sections'].get(classified.get('section_id'))
        output['section_mnemonic']=section.get('section_mnemonic') if section and section['register_id']==classified.get('register_id') else None
        # The original API chooses the last matching template when multiple exist.
        template=context['templates'].get((value['data_model_id'],classified.get('register_id')),{})
        output.update({field:template.get(field) for field in ['template_id','template_document_id']})
        return self.models.model('IngestionDataSearchResultData').model_validate(output).model_dump(mode='json')
    def outgoing_wire(self,value,context):
        output=dict(value);output['partner_mnemonic']=value.get('changed_by_partner_id')
        for kind,key,name in [('model','data_model_id','data_model_mnemonic'),('register','register_id','register_mnemonic')]:
            linked=context['catalog'].get((kind,value.get(key)));output[name]=linked.get(name) if linked else None
        topic=context['topics'].get(value.get('topic_id'));output['websub_topic']=topic.get('websub_topic') if topic else None
        return self.models.model('OutgestionDataSearchResultData').model_validate(output).model_dump(mode='json')
    def execute_request(self,path,p,actor,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_request(path,p,actor,pagination)
        incoming=path.startswith('/ingestion-data/');kind='incoming' if incoming else 'outgoing';op=path.rsplit('/',1)[-1]
        with self.engine.connect() as c:
            if op.endswith('summary_data'):
                criteria=messages.c.kind==kind;partner='partner_id' if incoming else 'topic_id'
                total,partners,models=c.execute(select(func.count(),func.count(func.distinct(messages.c.data[partner].astext)),func.count(func.distinct(messages.c.data['data_model_id'].astext))).where(criteria)).one()
                return {'no_of_messages':total,'no_of_partners' if incoming else 'no_of_topics':partners,'no_of_data_models':models},None
            if op in {'get_raw_payload','get_enriched_and_transformed_payload'}:
                value=self.message(c,'incoming-payload' if op=='get_raw_payload' else 'enriched',p['ingest_id']) or {}
                result={'raw_data_json':value.get('raw_data_json')} if op=='get_raw_payload' else {key:value.get(key) or None for key in ['enriched_data_json','transformed_data_json']}
                return self.models.model('IngestionDataPayload').model_validate(result).model_dump(mode='json'),None
            if pagination is None:raise RegistryError('SYS-ERR-001')
            raw=messages.alias('message');payload=messages.alias('payload');payload_kind=kind+'-payload'
            text=pagination.get('search_text');pattern='%'+('None' if text is None else text)+'%'
            criteria=(payload.c.kind==payload_kind)&payload.c.data['raw_data_text'].astext.ilike(pattern)
            total=c.execute(select(func.count()).select_from(payload).where(criteria)).scalar_one()
            join_key=raw.c.key if incoming else raw.c.data['payload_id'].astext
            query=select(raw.c.data).select_from(raw.join(payload,join_key==payload.c.key)).where(raw.c.kind==kind,criteria)
            sort=pagination.get('sort_by');field='receipt_date_time' if incoming else 'created_at';direction='desc';contract=self.message_contract()
            if sort:
                parts=sort.split(':')
                if len(parts)>2:raise RegistryError('SYS-ERR-001')
                field=parts[0];direction=parts[1] if len(parts)==2 else 'desc'
            alias=raw;sort_kind=kind
            if field not in contract[kind]['columns']:
                if field in contract[payload_kind]['columns']:alias=payload;sort_kind=payload_kind
                else:field='receipt_date_time' if incoming else 'created_at'
            order=self.message_field(alias,sort_kind,field);query=query.order_by(order.desc() if direction.lower()=='desc' else order.asc()).offset((pagination['current_page']-1)*pagination['page_size']).limit(pagination['page_size'])
            wire=self.incoming_wire if incoming else self.outgoing_wire
            values=list(c.execute(query).scalars());context=self.page_context(c,kind,values)
            return [wire(value,context) for value in values],{'number_of_items':total,'number_of_pages':(total+pagination['page_size']-1)//pagination['page_size'] if total else 0}
