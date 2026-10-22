"""Own parameterized register and change-request search with schema filters."""
import json
from pathlib import Path
from sqlalchemy import select,func,cast,Numeric,Boolean,DateTime,JSON,text
from registry_hierarchy_store import RegistryHierarchyStore
from registry_record_store import records,record_timestamp
from registry_row_store import rows
from registry_document_store import documents
from registry_metadata_store import RegistryError
from registry_metadata_api import RegistryPrincipal
from registry_data_policy import RecordPolicyCompiler

SUPPORTED_PATHS=frozenset(['/register-data/search_in_a_register','/change-requests/search_in_change_request'])

def filter_conditions(schema,columns,value,table=records):
    if not value:return []
    if isinstance(value,str):
        try:value=json.loads(value)
        except json.JSONDecodeError as error:raise ValueError('Invalid filter_by JSON string: '+str(error)) from None
        if not isinstance(value,dict):return []
    if len(value)>10:raise ValueError('Too many filter fields. Maximum: 10')
    allowed={item['field_name']:item for item in schema or []};compiler=RecordPolicyCompiler(table,columns);result=[]
    for field,operators in value.items():
        config=allowed.get(field)
        if config is None or field not in columns:continue
        simple=not isinstance(operators,dict);operators={'eq':operators} if simple else operators
        if len(operators)>3:raise ValueError(f'Too many operators for field {field}. Maximum: 3')
        for op,item in operators.items():
            if op not in config.get('allowed_operators',[]):continue
            kind=config.get('filter_type');pair=op=='between';comparison=op in {'gt','gte','lt','lte','eq','neq'}
            if op in {'in','nin'}:
                if not isinstance(item,list):raise ValueError(f"Operator '{op}' requires a list value")
                if len(item)>100:raise ValueError(f'IN list too large for {field}. Maximum: 100')
            if kind in {'number_range','date_range'} and pair and (not isinstance(item,(list,tuple)) or len(item)!=2):raise ValueError(f"Operator 'between' requires a list of 2 values for {field}")
            values=item if pair and kind in {'number_range','date_range'} else [item]
            if kind=='number_range' and (pair or comparison) and any(v is not None and not isinstance(v,(int,float)) for v in values):raise ValueError(f'Invalid type for numeric filter on {field}')
            if kind=='date_range' and (pair or comparison):
                for v in values:
                    if v is None:continue
                    if not isinstance(v,str):raise ValueError(f'Invalid date type for {field}. Expected string or datetime')
                    try:record_timestamp(v)
                    except ValueError:raise ValueError(f'Invalid date format for {field}. Use ISO format (YYYY-MM-DD)') from None
            if kind=='dropdown' and config.get('options'):
                options=[entry['value'] for entry in config['options']]
                if op=='eq' and item not in options:raise ValueError(f"Invalid option '{item}' for {field}")
                if op=='in' and any(v not in options for v in item):raise ValueError(f'Invalid options {[v for v in item if v not in options]} for {field}')
            if kind=='boolean' and not isinstance(item,bool):raise ValueError(f'Boolean value required for {field}')
            if kind=='date_range' and not simple:
                item=[record_timestamp(v).date() if isinstance(v,str) else v for v in item] if isinstance(item,list) else (record_timestamp(item).date() if isinstance(item,str) else item)
            column,_=compiler.column(field)
            if op=='eq':condition=column==item
            elif op=='neq':condition=column!=item
            elif op in {'in','nin'}:condition=column.in_(item) if op=='in' else ~column.in_(item)
            elif op in {'contains','ncontains','startsWith','endsWith'}:
                pattern={'contains':'%'+str(item)+'%','ncontains':'%'+str(item)+'%','startsWith':str(item)+'%','endsWith':'%'+str(item)}[op];condition=column.ilike(pattern)
                if op=='ncontains':condition=~condition
            elif op in {'gt','gte','lt','lte'}:condition={'gt':column.__gt__,'gte':column.__ge__,'lt':column.__lt__,'lte':column.__le__}[op](item)
            elif pair and isinstance(item,(list,tuple)) and len(item)==2:condition=column.between(*item)
            elif op=='isNull':condition=column.is_(None) if item else column.is_not(None)
            else:continue
            result.append(condition)
    return result

class RegistrySearchStore(RegistryHierarchyStore):
    def initialize(self):
        super().initialize()
        # Parent initialization rejects any database outside the candidate
        # namespace. These indexes never modify a live source database.
        with self.engine.begin() as c:
            c.execute(text('CREATE EXTENSION IF NOT EXISTS pg_trgm'))
            c.execute(text("CREATE INDEX IF NOT EXISTS ix_console_record_search_text ON console_record_snapshots USING gin ((data->>'search_text') gin_trgm_ops) WHERE kind='current'"))
            c.execute(text("CREATE INDEX IF NOT EXISTS ix_console_change_payload_search_text ON console_registry_rows USING gin ((data->>'search_text') gin_trgm_ops) WHERE kind='change-payload'"))
    def execute_policy_request(self,path,p,principal,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_policy_request(path,p,principal,pagination)
        if not isinstance(principal,RegistryPrincipal):raise ValueError('Trusted search principal required')
        if pagination is None:raise RegistryError('SYS-ERR-001')
        page=pagination['current_page'];size=pagination['page_size'];text=pagination.get('search_text');sort=pagination.get('sort_by')
        with self.engine.connect() as c:
            if path.endswith('/search_in_change_request'):return self.search_changes(c,principal,pagination)
            definition=self.require_definition(c,p['register_id']);interface=self.record_interface(definition)
            if not interface or not interface['extension_current_available']:self.fail('REGISTER_DATA_NOT_FOUND','Register implementation not found for '+definition['register_mnemonic'])
            columns=interface['current']['columns'];schema=self.state(c,p['register_id']).get('schema') or {};filters=pagination.get('filter_by');condition=[records.c.kind=='current',records.c.register_id==p['register_id'],records.c.data['search_text'].astext.ilike('%'+str(text)+'%')]
            parsed=filters
            if isinstance(parsed,str):
                try:parsed=json.loads(parsed)
                except json.JSONDecodeError:parsed=None
            if not isinstance(parsed,dict) or 'record_status' not in parsed:condition.append(records.c.data['record_status'].astext=='ACTIVE')
            try:condition.extend(filter_conditions(schema.get('filter_schema'),columns,filters))
            except ValueError as error:self.fail('INVALID_REQUEST',str(error))
            policy=self.record_policy(definition,principal.data_policies)
            if policy is not None:condition.append(policy)
            total=c.execute(select(func.count()).select_from(records).where(*condition)).scalar_one();name=sort.lstrip('-') if sort else None;descending=bool(sort and sort.startswith('-'))
            if name not in columns:name='last_approved_at';descending=True
            order,_=RecordPolicyCompiler(records,columns).column(name);query=select(records.c.source_json,records.c.data).where(*condition).order_by(order.desc() if descending else order.asc())
            if name!='internal_record_id':query=query.order_by(records.c.record_id.asc())
            values=[]
            for original,projection in c.execute(query.offset((page-1)*size).limit(size)):
                value=self.record_value(original,columns)
                # PostgreSQL JSONB has a canonical key order, which matters
                # when the legacy display contract stringifies an object.
                for field,meta in columns.items():
                    if meta['type']=='jsonb':value[field]=projection.get(field)
                values.append(value)
            ids={value['record_image_document_id'] for value in values if value.get('record_image_document_id')};catalog={value['document_id']:value for value in c.execute(select(documents.c.data).where(documents.c.kind=='catalog',documents.c.state=='READY',documents.c.id.in_(ids))).scalars()} if ids else {}
            fields=sorted(schema.get('search_result_schema') or [],key=lambda item:item.get('order',999));result=[]
            for value in values:
                item={field:value.get(field) for field in self.models.definitions['SearchResultData']['properties']};display=[]
                for field in fields:
                    selected=value.get(field['field_name']);display.append({'field_name':field['field_name'],'value':str(selected) if selected is not None else None,'order':field.get('order',999)})
                image=catalog.get(value.get('record_image_document_id'));item['record_image_url']=self.storage.get_url(image['document_store_id'],image['bucket']) if image else None;item['display_fields']=display or None
                result.append(self.models.model('SearchResultData').model_validate(item).model_dump(mode='json'))
            return result,{'number_of_items':total,'number_of_pages':(total+size-1)//size}
    def search_changes(self,c,principal,pagination):
        payload=rows.alias('searched_payload');joined=rows.join(payload,(payload.c.kind=='change-payload') & (rows.c.data['change_request_id'].astext==payload.c.data['change_request_id'].astext));condition=[rows.c.kind=='change',payload.c.data['search_text'].astext.ilike('%'+str(pagination.get('search_text'))+'%')];policy=self.change_search_policy(c,principal.data_policies)
        if policy is not None:condition.append(policy)
        contract=json.loads(Path(__file__).with_name('registry_row_contract.json').read_text());raw=str(pagination.get('sort_by') or '').strip();field=None;descending=True
        if raw:
            if ':' in raw:field,direction=raw.split(':',1);field=field.strip().lstrip('-');descending=direction.strip().lower()=='desc'
            else:field=raw.lstrip('-').strip();descending=raw.startswith('-')
        if not field:field='created_at';descending=True
        table=rows if field in contract['change']['columns'] else payload
        meta=contract['change' if table is rows else 'change-payload']['columns'].get(field)
        if meta is None:field='created_at';table=rows;meta=contract['change']['columns'][field]
        typ=meta['type'];column=table.c.data[field].astext
        if typ.startswith('timestamp'):column=cast(column,DateTime)
        elif typ in {'smallint','integer','bigint','numeric','double precision','real'}:column=cast(column,Numeric)
        elif typ=='boolean':column=cast(column,Boolean)
        elif typ in {'json','jsonb'}:column=cast(table.c.data[field],JSON)
        total=c.execute(select(func.count()).select_from(joined).where(*condition)).scalar_one();size=pagination['page_size'];values=c.execute(select(rows.c.data,payload.c.data).select_from(joined).where(*condition).order_by(column.desc() if descending else column.asc()).offset((pagination['current_page']-1)*size).limit(size)).all();definitions={value['register_id']:value for value in self.definitions(c)};sections={value['section_id']:value for value in self.rows(c,'section')};tabs={value['tab_id']:value for value in self.rows(c,'tab')};result=[]
        for value,body in values:
            definition=definitions.get(value['register_id']);section=sections.get(value['section_id']);tab=tabs.get(value['tab_id'])
            if not definition or not section or not tab:raise RegistryError('SYS-ERR-001')
            item={name:value.get(name) for name in self.models.definitions['ChangeRequestSearchResultData']['properties']};item.update(register_mnemonic=definition['register_mnemonic'],section_mnemonic=section['section_mnemonic'],tab_label=tab['tab_label'],change_payload=body.get('change_payload'))
            for name in ['created_at','approved_at']:item[name]=record_timestamp(value[name]).isoformat() if value.get(name) else None
            result.append(self.models.model('ChangeRequestSearchResultData').model_validate(item).model_dump(mode='json'))
        return result,{'number_of_items':total,'number_of_pages':(total+size-1)//size}
