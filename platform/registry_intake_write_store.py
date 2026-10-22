"""Own transactional draft saves with parent resolution and document replacement."""
import datetime,decimal,hashlib,json,uuid
from functools import cached_property
from pathlib import Path
from sqlalchemy import select,delete,update,Index,cast,literal,Text,Numeric,func,ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from registry_change_creation_store import RegistryChangeCreationStore
from registry_intake_record_store import intake_records
from registry_row_store import rows
from registry_record_store import records
from registry_layout_store import layouts
from registry_document_store import documents
from registry_metadata_api import RegistryPrincipal,RegistryAuthError
from registry_metadata_store import RegistryError
from registry_data_policy import RecordPolicyCompiler
from registry_domain_validation import validate_domain
from registry_application_reference import application_reference

SAVE_PATH='/intake-form-data/save_intake_form_submission'
SUPPORTED_PATHS=frozenset([SAVE_PATH])
class RegistryIntakeWriteStore(RegistryChangeCreationStore):
    def __init__(self,*args,uuid_factory=None,reference_factory=None,geo_hierarchy=None,**kwargs):
        super().__init__(*args,**kwargs);self.uuid_factory=uuid_factory or uuid.uuid4;self.reference_factory=reference_factory;self.geo_hierarchy=geo_hierarchy
    @cached_property
    def intake_write_contract(self):return json.loads(Path(__file__).with_name('registry_intake_write_contract.json').read_text())
    def record_value(self,original,columns):
        value=super().record_value(original,columns)
        if any(meta and meta['columns'] is columns for meta in self.intake_contract.values()):
            for field,column in columns.items():
                if column['type']=='numeric' and value.get(field) is not None:value[field]=decimal.Decimal(value[field])
        return value
    def initialize(self):
        super().initialize()
        Index('ux_console_intake_application_reference',rows.c.data['application_reference'].astext,unique=True,postgresql_where=rows.c.kind=='intake').create(self.engine,checkfirst=True)
        for register,meta in self.intake_contract.items():
            if not meta:continue
            definition=next((d for d in self.record_contracts().values() if d['register_id']==register),None)
            if definition is None:continue
            # Names come from captured database metadata, never a request.
            with self.engine.connect() as c:d=self.definition(c,'register',register)
            if d is None:continue
            for unique in self.intake_write_contract['interfaces'].get(d['register_mnemonic'],{}).get('unique',[]):
                name='ux_console_intake_'+hashlib.sha256(json.dumps([register,unique]).encode()).hexdigest()[:18]
                Index(name,*(intake_records.c.data[field].astext for field in unique),unique=True,postgresql_where=intake_records.c.register_id==register).create(self.engine,checkfirst=True)
    def draft_defaults(self,columns,defaults):
        return {field:meta.get('default',meta.get('server_default')) for field in columns if (meta:=defaults.get(field,{}))}
    def validate_form_write(self,c,form,register):
        value=self.definition(c,'form',form)
        if value is None:self.fail('REQUEST_VALIDATION_ERROR',f"Intake form '{form}' was not found")
        if register and value['register_id']!=register:self.fail('REQUEST_VALIDATION_ERROR',f"Intake form '{form}' does not belong to register '{register}'")
        return value
    def save_snapshot(self,c,register,value,new=False,nulls=None):
        # Serialize exact decimal values through PostgreSQL instead of floats.
        raw=json.dumps(value,default=lambda v:str(v) if isinstance(v,(datetime.date,datetime.datetime,decimal.Decimal)) else v)
        expression=cast(literal(raw),JSONB)
        with_defaults=self.intake_write_contract['domain_defaults'][self.require_definition(c,register)['register_mnemonic']]
        for field,column in self.intake_contract[register]['columns'].items():
            if column['type']=='numeric' and value.get(field) is not None:
                default=with_defaults.get(field,{});number=cast(literal(str(value[field])),Numeric(default.get('numeric_precision'),default.get('numeric_scale')))
                expression=func.jsonb_set(expression,literal([field],type_=ARRAY(Text)),func.to_jsonb(number))
        raw=c.execute(select(cast(expression,Text))).scalar_one()
        attrs=self.intake_snapshot_values(register,raw,nulls)
        if new:self.insert_intake_snapshots(c,[attrs])
        else:c.execute(update(intake_records).where(intake_records.c.register_id==register,intake_records.c.key==attrs['key']).values(**attrs,data=cast(literal(raw),JSONB)))
    def normalize_intake_value(self,value,meta):
        if value is None:return None
        typ=meta['type']
        if typ in {'character varying','text','USER-DEFINED'}:
            if not isinstance(value,str):raise RegistryError('SYS-ERR-001')
        elif typ in {'integer','bigint','smallint'}:
            if not isinstance(value,int) or isinstance(value,bool):raise RegistryError('SYS-ERR-001')
            if not -(2**(63 if typ=='bigint' else 15 if typ=='smallint' else 31))<=value<2**(63 if typ=='bigint' else 15 if typ=='smallint' else 31):raise RegistryError('SYS-ERR-001')
        elif typ in {'numeric','double precision','real'}:
            if isinstance(value,bool) or not isinstance(value,(int,float,decimal.Decimal,str) if typ=='numeric' else (int,float,decimal.Decimal)):raise RegistryError('SYS-ERR-001')
            if typ=='numeric':value=decimal.Decimal(value)
        elif typ=='boolean':
            if not isinstance(value,bool):raise RegistryError('SYS-ERR-001')
        elif typ=='date':
            if isinstance(value,str):value=datetime.datetime.strptime(value,'%Y-%m-%d').date() if value.strip() else None
            if value is not None and not isinstance(value,datetime.date):raise RegistryError('SYS-ERR-001')
            value=value.isoformat() if value else None
        elif typ.startswith('timestamp'):
            if not isinstance(value,datetime.datetime):raise RegistryError('SYS-ERR-001')
            value=value.isoformat()
        elif typ=='uuid':value=str(uuid.UUID(str(value)))
        elif typ not in {'json','jsonb'}:raise RegistryAuthError(503,'Intake column interface is unavailable')
        if meta.get('max_length') and value is not None and len(value)>meta['max_length']:raise RegistryError('SYS-ERR-001')
        return value
    def intake_row_scope(self,c,register,value,policies):
        raw=json.dumps(value,default=str);meta=self.intake_interface(c,register);nulls=[name for name,col in meta['columns'].items() if col['type'] in {'json','jsonb'} and value.get(name) is None]
        candidate=select(cast(literal(raw),JSONB).label('data'),literal(raw,type_=Text).label('source_json'),literal(nulls,type_=JSONB).label('json_null_fields')).subquery();condition=RecordPolicyCompiler(candidate,meta['columns']).resolve(policies,register)
        if condition is not None and not c.execute(select(condition.is_(True))).scalar_one():self.fail('RECORD_ACCESS_DENIED')
    def parent_link(self,c,submission,form_register,definition,payload,existing,policies):
        parent=definition.get('master_register_id')
        if parent is None:return None
        if 'link_internal_record_id' not in payload and existing is not None:return existing
        value=payload.get('link_internal_record_id');value=None if value is None or isinstance(value,str) and not value.strip() else str(value)
        candidates=list(c.execute(select(intake_records.c.data).where(intake_records.c.register_id==parent,intake_records.c.submission_id==str(submission))).scalars());ids={r['internal_record_id'] for r in candidates};optional=definition['register_id']==form_register
        if value:
            if value in ids:
                self.intake_row_scope(c,parent,next(r for r in candidates if r['internal_record_id']==value),policies);return value
            if optional:
                parent_def=self.require_definition(c,parent);query=select(records.c.data).where(records.c.kind=='current',records.c.register_id==parent,records.c.record_id==value)
                if c.execute(query).first():self.require_readable_subject(c,parent,value,policies);return value
                self.fail('INVALID_REQUEST',f"link_internal_record_id '{value}' does not exist in register '{parent_def['register_mnemonic']}'")
            self.fail('INVALID_REQUEST',f"link_internal_record_id '{value}' is not an allowed parent for this submission")
        if len(ids)==1:
            self.intake_row_scope(c,parent,candidates[0],policies);return next(iter(ids))
        if not ids and not optional:self.fail('INVALID_REQUEST',f"No parent records exist in this submission; cannot link child row for register '{definition['register_mnemonic']}'")
        if len(ids)>1 and not optional:self.fail('INVALID_REQUEST','link_internal_record_id is required when multiple parent records exist in this submission')
        return None
    def intake_display(self,value,mnemonic):
        hooks=self.intake_write_contract['interfaces'][mnemonic]['hooks'];domain=self.creation_contract['domains'].get(mnemonic,{})
        def render(method):
            parts=[]
            for hook in hooks[method]:
                if 'domain' in hook:
                    method=hook['domain'];fields=domain.get(method,domain.get('construct_record_name',[]) if method=='construct_intake_record_name' else [])
                    text=' '.join(str(value.get(k) or '').strip() for k in fields if str(value.get(k) or '').strip())
                    if method=='construct_intake_record_name' and method not in domain:
                        reference=str(value.get('application_reference') or '').strip()
                        if reference and reference not in text:text=(text+' '+reference).strip()
                    if text:parts.append(text)
                else:parts.extend(value.get(k) or '' for k in hook['fields'])
            return ' '.join(filter(None,parts)).strip()
        if 'search_text' in value:value['search_text']=render('get_search_text_fields') or None
        name=render('get_record_name_fields')
        if name and 'record_name' in value:value['record_name']=name
        return value
    def execute_policy_request(self,path,p,principal,pagination=None):
        if path!=SAVE_PATH:return super().execute_policy_request(path,p,principal,pagination)
        if not isinstance(principal,RegistryPrincipal):raise ValueError('Verified intake principal required')
        actor=principal.name or principal.subject
        with self.engine.begin() as c:
            if p.get('submission_id'):
                submission=self.intake_meta(c,p['submission_id'],lock=True);self.full_intake_scope(c,submission,principal.data_policies)
                if submission['draft_status']!='DRAFT':self.fail('INTAKE_FORM_INVALID_STATE',f"Submission '{p['submission_id']}' can only be saved while in DRAFT state")
                if submission['form_id']!=p['form_id'] or submission['register_id']!=p['register_id']:self.fail('REQUEST_VALIDATION_ERROR','Saving cannot reassign an existing submission to another form or register')
            else:
                stamp=self.clock();form=self.validate_form_write(c,p['form_id'],p['register_id']);columns=json.loads(Path(__file__).with_name('registry_row_contract.json').read_text())['intake']['columns'];submission={field:None for field in columns};submission.update(self.draft_defaults(columns,self.intake_write_contract['submission_defaults']));submission.update(submission_id=str(self.uuid_factory()),application_reference=self.reference_factory() if self.reference_factory else application_reference(self.intake_write_contract['application_reference_format']),form_id=p['form_id'],register_id=p['register_id'],created_by=actor,submission_source='STAFF_PORTAL',first_created_at=stamp.isoformat(),last_updated_at=stamp.isoformat(),number_of_verifications_required=form.get('number_of_verifications') or 0);self.put_row(c,'intake',submission,True)
            section=c.execute(select(layouts.c.data).where(layouts.c.kind=='section',layouts.c.id==p['section_id'])).scalar_one_or_none()
            if section is None:self.fail('REQUEST_VALIDATION_ERROR',f"Section '{p['section_id']}' was not found")
            definition=self.definition(c,'register',p['section_register_id'])
            if definition is None:self.fail('REGISTER_NOT_FOUND')
            meta=self.intake_interface(c,p['section_register_id']);mnemonic=definition['register_mnemonic'];defaults=self.intake_write_contract['domain_defaults'][mnemonic];cols={k:{**v,**defaults.get(k,{})} for k,v in meta['columns'].items()}
            if section['section_register_id']!=p['section_register_id'] or p['section_id'] not in {s['section_id'] for s,_ in self.submission_sections(c,p['form_id'])}:self.fail('REQUEST_VALIDATION_ERROR','Section does not belong to the supplied intake form and section register')
            proposals=p.get('section_payload') or [];self.validate_coded_values(section,proposals);validate_domain(mnemonic,proposals)
            old={v['internal_record_id']:v for original in c.execute(select(intake_records.c.source_json).where(intake_records.c.register_id==p['section_register_id'],intake_records.c.submission_id==submission['submission_id'])).scalars() if (v:=self.record_value(original,meta['columns']))};incoming=set();pending={};new_values=[]
            for payload in proposals:
                if payload.get('edit_action')=='DELETE':continue
                key=payload.get('internal_record_id') or str(self.uuid_factory());incoming.add(key);existing=old.get(key);data={name:value for name,value in payload.items() if name in cols};data['internal_record_id']=key;data['submission_id']=submission['submission_id'];data['application_reference']=submission['application_reference']
                for name,value in [('created_by',actor),('created_at',datetime.datetime.fromisoformat(submission['first_created_at'])),('last_approved_by',actor),('last_approved_at',datetime.datetime.fromisoformat(submission['last_updated_at']))]:
                    if name in cols:data[name]=value
                if 'link_internal_record_id' in cols:data['link_internal_record_id']=self.parent_link(c,submission['submission_id'],p['register_id'],definition,payload,(existing or {}).get('link_internal_record_id'),principal.data_policies)
                if 'geo_lowest_level_value_id' in data:
                    # Preserve source assignment order for explicit hierarchy
                    # fields; enrichment uses a configured server transport.
                    if 'geo_code_hierarchy_json' not in payload or list(payload).index('geo_code_hierarchy_json')<list(payload).index('geo_lowest_level_value_id'):data['geo_code_hierarchy_json']=self.geo_hierarchy(data['geo_lowest_level_value_id']) if self.geo_hierarchy and data['geo_lowest_level_value_id'] else None
                if existing:
                    for name in ['internal_record_id','submission_id','section_id']:data.pop(name,None)
                normalized={name:self.normalize_intake_value(value,cols[name]) for name,value in data.items()}
                if existing:
                    for field,raw in data.items():
                        if cols[field]['type']=='numeric' and existing.get(field)==raw:normalized[field]=existing.get(field)
                value={**({name:None for name in cols} if existing is None else existing),**normalized}
                if existing is None:
                    for field,default in defaults.items():
                        if value.get(field) is None and ('default' in default or 'server_default' in default):value[field]=default.get('default',default.get('server_default'))
                for field,column in cols.items():
                    if not column['nullable'] and value.get(field) is None:raise RegistryError('SYS-ERR-001')
                if existing is None:new_values.append(value)
                else:pending[key]=value;old[key]=value
            for value,new in [(v,False) for v in pending.values()]+[(v,True) for v in new_values]:
                value=self.intake_display(value,mnemonic);self.intake_row_scope(c,p['section_register_id'],value,principal.data_policies);self.save_snapshot(c,p['section_register_id'],value,new=new)
            removed=set(old)-incoming
            c.execute(delete(intake_records).where(intake_records.c.register_id==p['section_register_id'],intake_records.c.submission_id==submission['submission_id'],intake_records.c.record_id.in_(removed)))
            if removed:
                for register,key,value in c.execute(select(intake_records.c.register_id,intake_records.c.key,intake_records.c.data).where(intake_records.c.submission_id==submission['submission_id'],intake_records.c.link_id.in_(removed))):
                    value={**value,'link_internal_record_id':None};self.intake_row_scope(c,register,value,principal.data_policies);self.save_snapshot(c,register,value)
            submission.update(form_id=p['form_id'],register_id=p['register_id'],draft_status='DRAFT',last_updated_at=self.clock().isoformat());self.put_row(c,'intake',submission)
            attachments=p.get('documents')
            if attachments is not None:
                desired={v['document_id']:v for v in attachments};existing=list(c.execute(select(documents.c.id,documents.c.data).where(documents.c.kind=='intake',documents.c.data['submission_id'].as_string()==submission['submission_id'])).all());own={value['document_id']:(key,value) for key,value in existing if value['section_id']==p['section_id']}
                if any(value['document_id'] in desired and value['section_id']!=p['section_id'] for key,value in existing):raise RegistryError('SYS-ERR-001')
                for key,value in own.values():
                    if value['document_id'] not in desired:c.execute(delete(documents).where(documents.c.kind=='intake',documents.c.id==key))
                    else:c.execute(update(documents).where(documents.c.kind=='intake',documents.c.id==key).values(data={**value,'label':desired[value['document_id']].get('label')}))
                self.find_documents(c,list(set(desired)-set(own)))
                for key in set(desired)-set(own):self.put_doc(c,'intake',str(uuid.uuid4()),{'submission_id':submission['submission_id'],'section_id':p['section_id'],'document_id':key,'label':desired[key].get('label')})
            submission=self.reconcile_summary(c,'intake',submission);sections=self.section_payloads(c,submission,principal.data_policies);name=next((record['record_name'] for section in sections for record in section['records'] if record.get('record_name')),None);result=self.submission_payload(submission,sections,name);self.record_decision(c,path,submission['submission_id'],principal,stamp=datetime.datetime.fromisoformat(submission['last_updated_at']))
            return result,None
