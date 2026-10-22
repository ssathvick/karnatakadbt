"""Own transactional normal/core change-request admission."""
import json,uuid
from functools import cached_property
from pathlib import Path
from sqlalchemy import select,text,literal,cast,Text
from sqlalchemy.dialects.postgresql import JSONB
from registry_workflow_store import RegistryWorkflowStore
from registry_row_store import rows
from registry_record_store import records
from registry_layout_store import layouts
from registry_metadata_api import RegistryPrincipal,RegistryAuthError
from registry_metadata_store import RegistryError
from registry_domain_validation import validate_domain,invalid
from registry_section_validation import validate_section_payload,paths
from registry_data_policy import RecordPolicyCompiler

SUPPORTED_PATHS=frozenset(['/change-requests/create_change_request','/change-requests-core-data/create_change_request_for_core_data'])
class RegistryChangeCreationStore(RegistryWorkflowStore):
    def __init__(self,*args,master_codes=None,**kwargs):super().__init__(*args,**kwargs);self.master_codes=master_codes
    @cached_property
    def creation_contract(self):return json.loads(Path(__file__).with_name('registry_change_creation_contract.json').read_text())
    def creation_layout(self,c,kind,key):
        value=c.execute(select(layouts.c.data).where(layouts.c.kind==kind,layouts.c.id==key)).scalar_one_or_none()
        if value is None:raise RegistryError('SECTION_NOT_FOUND' if kind=='section' else 'TAB_NOT_FOUND','Section not found' if kind=='section' else 'Tab not found')
        return value
    def validate_coded_values(self,section,proposals):
        if not self.creation_contract['validate_attribute_values']:return
        records=[p for p in proposals if p.get('edit_action')!='DELETE']
        if not records:return
        if self.master_codes is None:raise RegistryAuthError(503,'Authoritative attribute code service is unavailable')
        coded=self.master_codes.codes();mapping={}
        def walk(node):
            if isinstance(node,list):
                for n in node:walk(n)
            elif isinstance(node,dict):
                source=node.get('widget-data-source');params=source.get('params') if isinstance(source,dict) else None;attribute=params.get('attribute_id') if isinstance(params,dict) else None
                if isinstance(attribute,str) and attribute:
                    if isinstance(node.get('column-key'),str) and node['column-key']:mapping[node['column-key']]=attribute
                    else:
                        for field in paths(node.get('widget-data-path')):
                            field=field.rsplit('.',1)[-1].strip()
                            if field:mapping[field]=attribute
                for value in node.values():walk(value)
        if not coded:invalid('Attribute validation is enabled, but Master Data has no attribute values configured')
        walk(section.get('section_ui_schema'));problems=[]
        for index,record in enumerate(records):
            for field,raw in record.items():
                attribute=mapping.get(field);permitted=coded.get(attribute)
                if not permitted:continue
                for value in raw if isinstance(raw,(list,tuple,set)) else [raw]:
                    if isinstance(value,str) and value and value not in permitted:problems.append(f"record {index}: {field}={value!r} is not a value of {attribute} (permitted: {', '.join(sorted(permitted))})")
        if problems:invalid('; '.join(problems))
    def proposed_scope(self,c,definition,proposal,policies,subject):
        key=proposal.get('internal_record_id') or (subject if definition['register_purpose']=='REGISTER' else None)
        existing=c.execute(select(records.c.data).where(records.c.kind=='current',records.c.register_id==definition['register_id'],records.c.record_id==key)).scalar_one_or_none() if key else None
        value={**(existing or {}),**proposal};raw=json.dumps(value)
        interface=self.record_interface(definition)['current'];nulls=[field for field,meta in interface['columns'].items() if meta['type'] in {'json','jsonb'} and value.get(field) is None]
        candidate=select(cast(literal(raw),JSONB).label('data'),literal(raw,type_=Text).label('source_json'),literal(nulls,type_=JSONB).label('json_null_fields')).subquery()
        condition=RecordPolicyCompiler(candidate,interface['columns']).resolve(policies,definition['register_id'])
        if condition is not None and not c.execute(select(condition.is_(True))).scalar_one():self.fail('RECORD_ACCESS_DENIED')
    def display_metadata(self,c,definition,proposals):
        domain=self.creation_contract['domains'].get(definition['register_mnemonic'],{});display=[]
        for proposal in proposals:
            existing=None
            if proposal.get('edit_action')=='UPDATE' and proposal.get('internal_record_id'):
                existing=c.execute(select(records.c.data).where(records.c.kind=='current',records.c.register_id==definition['register_id'],records.c.record_id==proposal['internal_record_id'])).scalar_one_or_none()
            display.append({**(existing or {}),**proposal})
        def render(value,fields,extra=()):return ' '.join([str(v).strip() for v in extra if str(v).strip()]+[str(value.get(k) or '').strip() for k in fields if str(value.get(k) or '').strip()]).strip()
        name=next((n for r in display if (n:=render(r,domain.get('construct_record_name',[])))),None)
        search=' '.join(t for r in display if (t:=render(r,domain.get('construct_search_text',[]),[name]))).strip() if domain else ''
        return name,search
    def execute_policy_request(self,path,p,principal,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_policy_request(path,p,principal,pagination)
        if not isinstance(principal,RegistryPrincipal):raise ValueError('Verified creation principal required')
        core=path.startswith('/change-requests-core-data/')
        with self.engine.begin() as c:
            def invalid(message):self.fail('INVALID_REQUEST',message)
            if core:
                if not p.get('section_id'):invalid('section_id is required for core-data change request operations')
                section=self.creation_layout(c,'section',p['section_id'])
                if not section['is_core_section']:self.fail('NON_CORE_SECTION_OPERATION_NOT_ALLOWED')
            definition=self.definition(c,'register',p.get('register_id'))
            if definition is None:self.fail('REGISTER_NOT_FOUND')
            section=self.creation_layout(c,'section',p.get('section_id'));self.creation_layout(c,'tab',p.get('tab_id'));child=self.definition(c,'register',section['section_register_id'])
            if child is None:self.fail('REGISTER_NOT_FOUND')
            if definition['register_purpose']!='REGISTER':invalid('Change request must belong to a register')
            if section['register_id']!=p.get('register_id'):invalid('Section does not belong to the specified register')
            if section['section_register_id']!=p.get('section_register_id'):invalid('Section Register does not match the one specified in the payload')
            if not p.get('internal_record_id'):invalid('Change request must have an internal_record_id to identify the subject record')
            if child['register_purpose']=='REGISTER' and child['register_id']!=definition['register_id']:invalid('Cross-register change requests are not allowed')
            proposals=p.get('change_payload') or []
            if not proposals:invalid('change_payload must contain at least one item.')
            for proposal in proposals:
                action=proposal['edit_action'];allowed={'UPDATE','NO_CHANGE'} if child['register_purpose']=='REGISTER' else {'ADD','UPDATE','DELETE','NO_CHANGE'}
                if action not in allowed:invalid(f'Action {action} is not allowed for this change request.')
                if child['register_purpose']=='TABLE':
                    if action in {'UPDATE','DELETE'} and not proposal.get('internal_record_id'):invalid(f'internal_record_id is required for table {action} payloads.')
                    if action=='ADD' and not proposal.get('link_internal_record_id'):invalid('link_internal_record_id is required for table ADD payloads.')
            interface=self.record_interface(child)
            if not interface or not interface.get('current'):raise RegistryAuthError(503,'Persisted section interface is unavailable')
            validate_section_payload(section,interface['current']['columns'],proposals,bool(p.get('documents')))
            # Serialize requests even when no pending row exists. Hash is
            # computed inside PostgreSQL; values remain bound parameters.
            c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),{'key':json.dumps([p['internal_record_id'],p['section_id']])})
            if c.execute(select(rows.c.key).where(rows.c.kind=='change',rows.c.record_id==p['internal_record_id'],rows.c.section_id==p['section_id'],rows.c.status=='PENDING').limit(1)).first():invalid('A pending change request already exists for this record and section')
            # Apply authoritative restrictions to the subject and every
            # existing child touched by the proposed operation.
            self.require_readable_subject(c,definition['register_id'],p['internal_record_id'],principal.data_policies) if principal.data_policies else None
            if principal.data_policies:
                for proposal in proposals:
                    key=proposal.get('internal_record_id')
                    if key and proposal['edit_action'] in {'UPDATE','DELETE','NO_CHANGE'}:self.require_readable_subject(c,child['register_id'],key,principal.data_policies)
                    if proposal.get('link_internal_record_id') and child.get('master_register_id'):self.require_readable_subject(c,child['master_register_id'],proposal['link_internal_record_id'],principal.data_policies)
                    if proposal['edit_action']!='DELETE':self.proposed_scope(c,child,proposal,principal.data_policies,p['internal_record_id'])
            self.validate_coded_values(section,proposals);validate_domain(child['register_mnemonic'],proposals)
            name,search=self.display_metadata(c,child,proposals);stamp=self.clock();key=str(uuid.uuid4());contract=json.loads(Path(__file__).with_name('registry_row_contract.json').read_text());value={field:None for field in contract['change']['columns']}
            value.update(change_request_id=key,record_name=name,register_id=p['register_id'],tab_id=p.get('tab_id'),section_id=p['section_id'],section_register_id=p['section_register_id'],internal_record_id=p['internal_record_id'],source_partner_id=principal.subject,change_request_source='STAFF_PORTAL',created_by=principal.name or principal.subject,created_at=stamp.isoformat(),no_of_verifications_required=section['no_of_verifications_required'],no_of_verifications_done=0,approval_status='PENDING')
            value.update(deduplication_change_request_status='PENDING',deduplication_register_status='PENDING')
            self.put_row(c,'change',value,True);self.put_row(c,'change-payload',{'change_request_id':key,'change_payload':proposals,'search_text':search},True)
            attachments=p.get('documents') or [];self.find_documents(c,[doc['document_id'] for doc in attachments])
            for doc in attachments:self.put_doc(c,'change',str(uuid.uuid4()),{'change_request_id':key,'document_id':doc['document_id'],'section_id':p['section_id'],'label':doc.get('label')})
            value=self.start_workflow(c,'change',value,principal,{'record_name':name,'section_mnemonic':section['section_mnemonic'],'register_mnemonic':definition['register_mnemonic'],'change_request_id':key},proposals)
            self.record_decision(c,path,key,principal,stamp=stamp)
            return self.reject_wire(value,core),None
