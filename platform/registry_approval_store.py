"""Native atomic normal/core approvals with durable downstream job admission."""
import copy,datetime,decimal,hashlib,json,re,uuid
from functools import cached_property
from pathlib import Path
from sqlalchemy import MetaData,Table,Column,String,Index,select,insert,update,delete,func,cast,literal,Text,Numeric,ARRAY,text
from sqlalchemy.dialects.postgresql import JSONB
from registry_registrant_auth_store import RegistryRegistrantAuthStore
from registry_record_store import records,record_timestamp
from registry_row_store import rows
from registry_layout_store import layouts
from registry_document_store import documents
from registry_score_config_store import scores
from registry_message_data_store import messages
from registry_metadata_store import RegistryError
from registry_metadata_api import RegistryPrincipal,RegistryAuthError
from registry_contract_models import ContractModels
from registry_approval_domain import ApprovalDomainHooks
from registry_approval_scoring import changed_paths,contributing_snapshot,should_queue

NORMAL_PATH='/change-requests/approve_change_request'
CORE_PATH='/change-requests-core-data/approve_change_request_for_core_data'
SUPPORTED_PATHS=frozenset([NORMAL_PATH,CORE_PATH])
metadata=MetaData()
approval_jobs=Table('console_registry_approval_jobs',metadata,Column('kind',String,primary_key=True),Column('id',String,primary_key=True),Column('data',JSONB,nullable=False))
Index('ix_console_approval_job_subject',approval_jobs.c.kind,approval_jobs.c.data['internal_record_id'].astext)
Index('ux_console_pending_approval_score',approval_jobs.c.data['link_internal_record_id'].astext,approval_jobs.c.data['score_type'].astext,unique=True,postgresql_where=(approval_jobs.c.kind=='score') & (approval_jobs.c.data['compute_status'].astext=='PENDING'))

class RegistryApprovalStore(RegistryRegistrantAuthStore):
    @cached_property
    def approval_contract(self):return json.loads(Path(__file__).with_name('registry_approval_contract.json').read_text())
    @cached_property
    def approval_models(self):
        definitions={}
        for name,schema in self.approval_contract['schemas'].items():definitions.update(schema.get('$defs',{}));definitions[name]=schema
        return ContractModels({'components':{'schemas':definitions}})
    def initialize(self):
        super().initialize();metadata.create_all(self.engine)
        Index('ux_console_pending_native_score',scores.c.data['link_internal_record_id'].as_string(),scores.c.data['score_type'].as_string(),unique=True,postgresql_where=(scores.c.kind=='queue') & (scores.c.data['compute_status'].as_string()=='PENDING')).create(self.engine,checkfirst=True)
        Index('ux_console_current_record',records.c.register_id,records.c.record_id,unique=True,postgresql_where=records.c.kind=='current').create(self.engine,checkfirst=True)
        for interface in self.record_contracts().values():
            mnemonic=next((name.removeprefix('G2PRegister') for name,model in self.approval_contract['models'].items() if model['table']==(interface.get('current') or {}).get('source_table')),None)
            if not mnemonic:continue
            for unique in self.approval_contract['models']['G2PRegister'+mnemonic].get('unique',[]):
                name='ux_console_current_'+hashlib.sha256(json.dumps([interface['register_id'],unique]).encode()).hexdigest()[:18]
                Index(name,*(records.c.data[field].astext for field in unique),unique=True,postgresql_where=(records.c.kind=='current') & (records.c.register_id==interface['register_id'])).create(self.engine,checkfirst=True)
    def approval_defaults(self,contract):
        result={}
        for field,meta in contract['columns'].items():
            if 'default' in meta:result[field]=meta['default']
            elif 'default_source' in meta:
                if 'uuid4' in meta['default_source']:result[field]=str(uuid.uuid4())
                elif 'datetime' in meta['default_source']:result[field]=self.clock().isoformat()
                else:raise RegistryAuthError(503,'Approval default interface is unavailable')
            elif 'server_default' in meta:
                raw=meta['server_default'].strip()
                result[field]={'false':False,'true':True}.get(raw)
                if raw not in {'false','true'}:
                    try:result[field]=int(raw)
                    except ValueError:raise RegistryAuthError(503,'Approval server default interface is unavailable') from None
            else:result[field]=None
        # Some legacy outgoing models evaluated datetime.now at import time.
        # Use the actual enqueue time instead of carrying that stale timestamp.
        if 'created_at' in result and contract['table']=='outgoing_raw_data':result['created_at']=self.clock().isoformat()
        return result
    def native_job(self,c,kind,model,fields):
        value={**self.approval_defaults(self.approval_contract['queues'][model]),**fields};key=value['queue_id']
        if kind=='score':self.put_score(c,'queue',value,new=True)
        else:c.execute(insert(approval_jobs).values(kind=kind,id=key,data=value))
        return value
    def current_display(self,value,mnemonic):
        hooks=self.approval_contract['models']['G2PRegister'+mnemonic]['hooks'];domain=self.creation_contract['domains'].get(mnemonic,{})
        def render(method):
            parts=[]
            for hook in hooks[method]:
                if 'construct_' in hook:
                    name='construct_record_name' if method=='get_record_name_fields' else 'construct_search_text'
                    fields=domain.get(name,[]);parts.append(' '.join(str(value.get(field) or '').strip() for field in fields if str(value.get(field) or '').strip()))
                elif 'self.functional_record_id' in hook:parts.extend([value.get('functional_record_id') or '',value.get('record_name') or ''])
                elif 'return []' not in hook:raise RegistryAuthError(503,'Approval display interface is unavailable')
            return ' '.join(filter(None,parts)).strip()
        # The ORM computes search_text before record_name on its write event.
        if 'search_text' in value:value['search_text']=render('get_search_text_fields') or None
        name=render('get_record_name_fields')
        if name and 'record_name' in value:value['record_name']=name
        return value
    def save_register_snapshot(self,c,definition,kind,value,new=False,existing=None,sql_null_fields=None):
        interface=self.record_interface(definition)[kind];model='G2PRegister'+('History' if kind=='history' else '')+definition['register_mnemonic'];contract=self.approval_contract['models'][model]
        normalized={}
        for field,column in interface['columns'].items():
            meta={**column,**{key:contract['columns'][field][key] for key in ['max_length'] if key in contract['columns'][field]}}
            val=value.get(field)
            if meta['type'].startswith('timestamp') and isinstance(val,str):val=record_timestamp(val)
            normalized[field]=self.normalize_intake_value(val,meta)
            if normalized[field] is None and not column['nullable']:raise RegistryError('SYS-ERR-001')
        raw=json.dumps(normalized,default=str);expression=cast(literal(raw),JSONB)
        for field,meta in contract['columns'].items():
            if field in normalized and normalized[field] is not None and interface['columns'][field]['type']=='numeric':
                expression=func.jsonb_set(expression,literal([field],type_=ARRAY(Text)),func.to_jsonb(cast(literal(str(normalized[field])),Numeric(meta.get('precision'),meta.get('scale')))))
        expression=cast(expression,JSONB)
        # Keep untouched values in PostgreSQL so large decimals retain precision.
        if existing is not None:
            changed={field for field in normalized if normalized[field]!=existing.get(field)}
            base=records.c.data
            for field in changed:base=func.jsonb_set(base,literal([field],type_=ARRAY(Text)),expression[field])
            raw=c.execute(select(cast(base,Text)).where(records.c.kind==kind,records.c.register_id==definition['register_id'],records.c.record_id==value['internal_record_id'])).scalar_one()
        else:raw=c.execute(select(cast(expression,Text))).scalar_one()
        if existing is not None and sql_null_fields is None:
            sql_null_fields=c.execute(select(records.c.json_null_fields).where(records.c.kind==kind,records.c.register_id==definition['register_id'],records.c.record_id==value['internal_record_id'])).scalar_one()
            if not isinstance(sql_null_fields,list):raise RegistryAuthError(503,'Record nullness metadata is unavailable')
            sql_null_fields=[field for field in sql_null_fields if normalized.get(field)==existing.get(field)]
        attrs=self.snapshot_values(definition['register_id'],kind,raw,sql_null_fields)
        if new:self.insert_snapshots(c,[attrs])
        else:
            attrs.pop('key');attrs['data']=cast(literal(raw),JSONB);c.execute(update(records).where(records.c.kind==kind,records.c.register_id==definition['register_id'],records.c.record_id==value['internal_record_id']).values(**attrs))
        return json.loads(raw)
    def approval_record(self,c,definition,key,lock=True):
        query=select(records.c.source_json).where(records.c.kind=='current',records.c.register_id==definition['register_id'],records.c.record_id==key)
        original=c.execute(query.with_for_update() if lock else query).scalar_one_or_none()
        return self.record_value(original,self.record_interface(definition)['current']['columns']) if original is not None else None
    def write_approval_records(self,c,change,section,payloads,policies):
        definition=self.require_definition(c,section['section_register_id']);mnemonic=definition['register_mnemonic'];model='G2PRegister'+mnemonic
        primary=section['section_register_id']==section['register_id']
        if primary and self.approval_record(c,definition,change['internal_record_id']) is None:self.fail('REGISTER_DATA_NOT_FOUND')
        modified=False
        for payload in payloads:
            action=payload.get('edit_action','UPDATE' if primary else 'ADD')
            if action=='NO_CHANGE':continue
            if primary:payload['internal_record_id']=change['internal_record_id'];modified=True
            key=payload.get('internal_record_id')
            if not primary and action=='ADD':
                if not payload.get('link_internal_record_id'):self.fail('INVALID_REQUEST','link_internal_record_id is required for table ADD change payloads.')
                key=key or str(uuid.uuid4());payload['internal_record_id']=key;modified=True
            elif not key:self.fail('INVALID_REQUEST',f'internal_record_id is required for table {action} change payloads.')
            existing=self.approval_record(c,definition,key)
            if not primary and action!='ADD' and existing is None:self.fail('REGISTER_DATA_NOT_FOUND')
            if not primary and action=='DELETE':
                if policies:self.require_readable_subject(c,definition['register_id'],key,policies)
                c.execute(delete(records).where(records.c.kind=='current',records.c.register_id==definition['register_id'],records.c.record_id==key));continue
            if not primary and action not in {'ADD','UPDATE'}:self.fail('INVALID_REQUEST',f'Unsupported table change payload action: {action}')
            parsed=self.approval_models.model('G2PRegisterSchema'+mnemonic).model_validate(payload).model_dump()
            if not primary and action=='ADD':
                value=self.approval_defaults(self.approval_contract['models'][model])
                fields={key:val for key,val in parsed.items() if val is not None and key in value}
                for key,val in payload.items():
                    if key in value and key not in fields:fields[key]=val
                value.update(fields)
                for field,meta in self.approval_contract['models'][model]['columns'].items():
                    if value[field] is None and 'default' in meta:value[field]=meta['default']
                value.update(created_by=change.get('created_by'),created_at=change.get('created_at'))
            else:
                value=dict(existing)
                for field,val in parsed.items():
                    if field in payload and field in value and field not in {'internal_record_id','edit_action'}:
                        if field=='link_internal_record_id' and not val:continue
                        value[field]=val
            for field,val in [('last_approved_at',change['approved_at']),('last_approved_by',change.get('approved_by') or 'system')]:
                if field in value:value[field]=val
            if policies:
                if existing:self.require_readable_subject(c,definition['register_id'],existing['internal_record_id'],policies)
                self.proposed_scope(c,definition,json.loads(json.dumps(value,default=str)),policies,change['internal_record_id'])
                if value.get('link_internal_record_id') and definition.get('master_register_id'):self.require_readable_subject(c,definition['master_register_id'],value['link_internal_record_id'],policies)
            value=self.current_display(value,mnemonic)
            new=not primary and action=='ADD'
            nulls=[field for field,meta in self.record_interface(definition)['current']['columns'].items() if meta['type'] in {'json','jsonb'} and value.get(field) is None and field not in fields] if new else None
            self.save_register_snapshot(c,definition,'current',value,new=new,existing=None if new else existing,sql_null_fields=nulls)
            modified=True
        return modified
    def approval_history(self,c,change,payloads):
        definition=self.require_definition(c,change['section_register_id'])
        if definition['register_purpose']=='PROGRAM_REGISTER':return
        mnemonic=definition['register_mnemonic'];model='G2PRegisterHistory'+mnemonic;contract=self.approval_contract['models'][model]
        for payload in payloads:
            if payload.get('edit_action')=='NO_CHANGE':continue
            parsed=self.approval_models.model('G2PRegisterHistorySchema'+mnemonic).model_validate(payload).model_dump()
            value=self.approval_defaults(contract);value.update({key:val for key,val in parsed.items() if val is not None and key in value})
            value.update(history_record_id=str(uuid.uuid4()),internal_record_id=payload.get('internal_record_id'),tab_id=change['tab_id'],section_id=change['section_id'],change_request_id=change['change_request_id'],created_at=change['created_at'],created_by=change['created_by'],approved_at=change['approved_at'],approved_by=change['approved_by'])
            for field,val in [('subject_internal_record_id',change['internal_record_id']),('change_request_source',change.get('change_request_source')),('is_primary_section',change.get('is_primary_section',False))]:
                if field in value:value[field]=val
            self.save_register_snapshot(c,definition,'history',value,new=True)
    def approval_documents(self,c,change,payloads):
        links=list(c.execute(select(documents.c.data).where(documents.c.kind=='change',documents.c.data['change_request_id'].as_string()==change['change_request_id'])).scalars())
        targets=list(dict.fromkeys(p['internal_record_id'] for p in payloads if p.get('edit_action','ADD') not in {'DELETE','NO_CHANGE'} and p.get('internal_record_id'))) or [change['internal_record_id']]
        for link in links:
            section=link.get('section_id') or change['section_id']
            for key in targets:
                history={**self.approval_defaults(self.approval_contract['queues']['G2PRegisterDocumentHistory']),'internal_record_id':key,'section_id':section,'document_id':link['document_id'],'label':link.get('label'),'change_request_id':change['change_request_id'],'change_request_source':change.get('change_request_source'),'created_by':change.get('created_by'),'created_at':change.get('created_at'),'approved_by':change.get('approved_by') or 'system','approved_at':change['approved_at']}
                self.put_doc(c,'history',str(uuid.uuid4()),history)
                existing=c.execute(select(documents.c.id,documents.c.data).where(documents.c.kind=='section',documents.c.data['internal_record_id'].as_string()==key,documents.c.data['document_id'].as_string()==link['document_id'])).first()
                if existing:c.execute(update(documents).where(documents.c.kind=='section',documents.c.id==existing.id).values(data={**existing.data,'section_id':section,'label':link.get('label')}))
                else:self.put_doc(c,'section',str(uuid.uuid4()),{**self.approval_defaults(self.approval_contract['queues']['G2PRegisterSectionDocument']),'internal_record_id':key,'document_id':link['document_id'],'section_id':section,'label':link.get('label')})
    def approval_score_jobs(self,c,change,section,payloads,score_only=False):
        parent=self.require_definition(c,change['register_id']);child=self.require_definition(c,change['section_register_id'])
        if not score_only and parent.get('completion_score_required') and parent['register_purpose']=='REGISTER' and (section['section_register_id']==section['register_id'] or section.get('is_list')):
            self.native_job(c,'completion','G2PCompletionScoreComputationQueue',{'register_id':parent['register_id'],'internal_record_id':change['internal_record_id'],'section_id':section['section_id'],'change_request_id':change['change_request_id']})
        if parent['register_mnemonic']!=child['register_mnemonic'] or child['register_purpose']!='REGISTER':return
        current=self.approval_record(c,child,change['internal_record_id'])
        if current is None:return
        touched=changed_paths(payloads)
        for definition in self.score_rows(c,'definition'):
            if definition['register_mnemonic']!=child['register_mnemonic'] or not definition['is_enabled']:continue
            paths=[attr['attribute_name'] for attr in self.score_rows(c,'attribute') if attr['register_mnemonic']==definition['register_mnemonic'] and attr['score_type']==definition['score_type']]
            if not paths:continue
            # Preserve Decimal values without passing unsupported objects to
            # the JSON queue encoder; equality uses the same default=str rule.
            snapshot=json.loads(json.dumps(contributing_snapshot(current,paths),default=str))
            condition=[scores.c.kind=='queue',scores.c.data['link_internal_record_id'].as_string()==change['internal_record_id'],scores.c.data['score_type'].as_string()==definition['score_type']]
            previous=c.execute(select(scores.c.data).where(*condition,scores.c.data['compute_status'].as_string()=='COMPLETED').order_by(scores.c.data['compute_latest_timestamp'].as_string().desc().nulls_first()).limit(1)).scalar_one_or_none()
            if not should_queue(snapshot,touched,previous.get('contributing_attribute_values') if previous else None):continue
            fields={'change_request_id':change['change_request_id'],'submission_id':'','link_internal_record_id':change['internal_record_id'],'contributing_attribute_values':snapshot,'compute_no_of_attempts':0,'compute_latest_timestamp':None,'compute_latest_error_code':None,'compute_status':'PENDING'}
            pending=c.execute(select(scores.c.id,scores.c.data).where(*condition,scores.c.data['compute_status'].as_string()=='PENDING').with_for_update()).first()
            if pending:self.put_score(c,'queue',{**pending.data,**fields})
            else:self.native_job(c,'score','G2PScoreComputeQueue',{'register_id':child['register_id'],'score_definition_id':definition['score_definition_id'],'score_type':definition['score_type'],**fields})
    def approval_outgoing_hierarchy(self,c,definition,key,visited=None):
        visited=set(visited or ());value=self.approval_record(c,definition,key,lock=False)
        if value is None:return None
        # RecordData's extra-field order follows the original model mapper.
        # Rebuild that order before creating the raw text used by integrations.
        columns=self.approval_contract['models']['G2PRegister'+definition['register_mnemonic']]['columns']
        base={field:value.get(field) for field in columns}
        links=list(c.execute(select(documents.c.data).where(documents.c.kind=='section',documents.c.data['internal_record_id'].as_string()==key,documents.c.state=='READY')).scalars())
        attached=[]
        for link in links:
            document=c.execute(select(documents.c.data).where(documents.c.kind=='catalog',documents.c.id==link['document_id'],documents.c.state=='READY')).scalar_one_or_none()
            if document:attached.append(self.doc_wire(document,link.get('section_id'),link.get('label')))
        base['documents']=attached
        # Source RecordData allows arbitrary domain fields and resolves its image.
        image=value.get('record_image_document_id')
        if image:
            document=c.execute(select(documents.c.data).where(documents.c.kind=='catalog',documents.c.id==image,documents.c.state=='READY')).scalar_one_or_none()
            base['record_image_url']=self.storage.get_url(document['document_store_id'],document['bucket']) if document else None
        base=self.models.model('RecordData').model_validate(base).model_dump(mode='json',exclude_unset=True)
        if definition['register_id'] in visited:return base
        visited.add(definition['register_id'])
        snake=lambda value:re.sub(r'(?<!^)(?=[A-Z])','_',value).lower()
        for child in self.definitions(c):
            if child.get('master_register_id')!=definition['register_id'] or child['register_id'] in visited:continue
            keys=list(c.execute(select(records.c.record_id).where(records.c.kind=='current',records.c.register_id==child['register_id'],records.c.link_id==key)).scalars())
            base[snake(child['register_mnemonic'])]=[self.approval_outgoing_hierarchy(c,child,item,visited) for item in keys]
        parent=self.definition(c,'register',definition.get('master_register_id')) if definition.get('master_register_id') else None
        if parent and parent['register_id'] not in visited and value.get('link_internal_record_id'):
            parent_value=self.approval_outgoing_hierarchy(c,parent,value['link_internal_record_id'],visited)
            if parent_value:base[snake(parent['register_mnemonic'])]=parent_value
        return base
    def approval_outgoing(self,c,change):
        definition=self.require_definition(c,change['register_id'])
        if not definition.get('outgest_applicable'):return
        topics=[row for row in self.message_rows(c,'topic') if row['register_id']==definition['register_id'] and row['is_active']]
        if not topics:return
        record=self.approval_outgoing_hierarchy(c,definition,change['internal_record_id'])
        if record is None:return
        payload_id=':'.join([change['change_request_id'],definition['register_id'],change['internal_record_id']])
        value={**self.approval_defaults(self.approval_contract['queues']['OutgoingRawDataPayload']),'payload_id':payload_id,'change_request_id':change['change_request_id'],'raw_data_json':record,'raw_data_text':json.dumps(record,default=str)}
        c.execute(insert(messages).values(kind='outgoing-payload',key=payload_id,data=value))
        partner=change.get('source_partner_id')
        if partner:
            if self.partner_client is None:raise RegistryAuthError(503,'Authoritative partner lookup is unavailable')
            partner=self.partner_client.require_active(partner)['partner_id']
        for topic in topics:
            value={**self.approval_defaults(self.approval_contract['queues']['OutgoingRawData']),'outgest_id':str(uuid.uuid4()),'payload_id':payload_id,'change_request_id':change['change_request_id'],'internal_record_id':change['internal_record_id'],'register_id':definition['register_id'],'data_model_id':topic['data_model_id'],'topic_id':topic['topic_id'],'changed_by':change.get('created_by'),'changed_at':change.get('created_at'),'approved_by':change.get('approved_by'),'approved_at':change.get('approved_at'),'changed_by_partner_id':partner}
            c.execute(insert(messages).values(kind='outgoing',key=value['outgest_id'],data=value))
    def approve_on_connection(self,c,key,principal,core=False,skip_verification=False):
        change=c.execute(select(rows.c.data).where(rows.c.kind=='change',rows.c.key==self.row_key('change',{'change_request_id':key})).with_for_update()).scalar_one_or_none()
        if change is None:self.fail('CHANGE_REQUEST_NOT_FOUND')
        change=dict(change)
        if change['approval_status']!='PENDING':self.fail('CHANGE_REQUEST_NOT_IN_PENDING_STATE')
        # Serialize approval and scoring updates for this subject, in addition
        # to the request and affected register rows locked by this transaction.
        c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:subject,0))'),{'subject':'registry-approve:'+change['internal_record_id']})
        if core and not change.get('section_id'):self.fail('INVALID_REQUEST','section_id is required for core-data change request operations')
        section=c.execute(select(layouts.c.data).where(layouts.c.kind=='section',layouts.c.id==change['section_id'])).scalar_one_or_none()
        if section is None:
            if core:raise RegistryError('SECTION_NOT_FOUND','Section not found')
            self.fail('SECTION_NOT_FOUND')
        if core and not section['is_core_section']:self.fail('NON_CORE_SECTION_OPERATION_NOT_ALLOWED')
        approved=c.execute(select(func.count()).select_from(rows).where(rows.c.kind=='verification',rows.c.data['change_request_id'].astext==key,rows.c.data['is_approved'].as_boolean().is_(True))).scalar_one()
        if not skip_verification and approved<(change.get('no_of_verifications_required') or 0):self.fail('VERIFICATIONS_PENDING')
        earlier=c.execute(select(rows.c.key).where(rows.c.kind=='change',rows.c.record_id==change['internal_record_id'],rows.c.status=='PENDING',rows.c.at<record_timestamp(change['created_at'])).limit(1)).first()
        if earlier:self.fail('REQUEST_VALIDATION_ERROR','There are earlier pending change requests for this record')
        payload=c.execute(select(rows.c.data).where(rows.c.kind=='change-payload',rows.c.data['change_request_id'].astext==key).with_for_update()).scalar_one_or_none()
        if payload is None:self.fail('INVALID_REQUEST',f'Change request payload not found for {key}.')
        payload=copy.deepcopy(payload);payloads=payload.get('change_payload') or []
        if not isinstance(payloads,list):raise RegistryError('SYS-ERR-001')
        if principal.data_policies:self.require_readable_subject(c,change['register_id'],change['internal_record_id'],principal.data_policies)
        stamp=self.clock();change.update(approval_status='APPROVED',approved_by='system' if core else principal.name or 'Unknown',approved_at=stamp.isoformat())
        child=self.require_definition(c,change['section_register_id']);hooks=None
        if child['register_mnemonic']=='Individual':
            household=next((d for d in self.definitions(c) if d['register_mnemonic']=='Household'),None)
            if household:
                hooks=ApprovalDomainHooks(child['register_id'],household['register_id']);affected=hooks.before(c,change['internal_record_id'],payloads,stamp.date())
                for household_id in affected:
                    existing=self.approval_record(c,household,household_id);display=self.current_display(dict(existing),'Household')
                    self.save_register_snapshot(c,household,'current',display,existing=existing)
        self.write_approval_records(c,change,section,payloads,principal.data_policies)
        self.put_row(c,'change-payload',payload)
        self.approval_history(c,change,payloads);self.approval_documents(c,change,payloads)
        if hooks:
            affected=hooks.after(c,change['internal_record_id'],payloads,record_timestamp(change['approved_at']))
            for household_id in affected:
                existing=self.approval_record(c,household,household_id);display=self.current_display(dict(existing),'Household')
                self.save_register_snapshot(c,household,'current',display,existing=existing)
        self.approval_score_jobs(c,change,section,payloads);self.approval_outgoing(c,change)
        self.put_row(c,'change',change);self.record_decision(c,CORE_PATH if core else NORMAL_PATH,key,principal,stamp=stamp)
        return change
    def execute_policy_request(self,path,p,principal,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_policy_request(path,p,principal,pagination)
        if not isinstance(principal,RegistryPrincipal):raise ValueError('Verified approval principal required')
        key=p.get('change_request_id');core=path==CORE_PATH
        if core and not key:self.fail('INVALID_REQUEST','change_request_id is required for core-data change request operations')
        with self.engine.begin() as c:value=self.approve_on_connection(c,key,principal,core)
        return self.reject_wire(value,core),None
