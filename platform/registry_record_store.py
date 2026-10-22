"""Own indexed current/history record snapshots and console version metadata."""
import datetime,hashlib,json,re
from functools import cached_property
from pathlib import Path
from sqlalchemy import MetaData,Table,Column,String,Text,DateTime,Index,select,insert,and_,or_,func,cast,bindparam,text
from sqlalchemy.dialects.postgresql import JSONB
from registry_topic_store import RegistryTopicStore
from registry_layout_store import layouts
from registry_row_store import rows
from registry_metadata_store import RegistryError

metadata=MetaData()
records=Table('console_record_snapshots',metadata,Column('kind',String,primary_key=True),Column('register_id',String,primary_key=True),Column('key',String,primary_key=True),Column('record_id',String),Column('link_id',String),Column('subject_id',String),Column('tab_id',String),Column('section_id',String),Column('created_at',DateTime),Column('approved_at',DateTime),Column('source_json',Text,nullable=False),Column('data',JSONB,nullable=False),Column('json_null_fields',JSONB))
Index('ix_console_record_id',records.c.kind,records.c.register_id,records.c.record_id)
Index('ix_console_record_link',records.c.kind,records.c.register_id,records.c.link_id)
Index('ix_console_record_subject_tab',records.c.kind,records.c.register_id,records.c.subject_id,records.c.tab_id)
Index('ix_console_record_history_time',records.c.kind,records.c.register_id,records.c.tab_id,records.c.section_id,records.c.created_at)
Index('ix_console_record_status',records.c.kind,records.c.register_id,records.c.data['record_status'].astext)
SUPPORTED_PATHS=frozenset('/register-data/'+name for name in ['get_number_of_versions','get_version_dates','get_versions_for_a_date','get_schema_definition_for_register_section'])

def record_timestamp(value):
    # PostgreSQL omits trailing fractional zeros; Python 3.10 accepts only
    # three or six fractional digits. Preserve values while padding for it.
    value=re.sub(r'\.(\d+)(?=[+-]\d\d:?\d\d$|$)',lambda match:'.'+match[1].ljust(6,'0'),value.replace('Z','+00:00'))
    return datetime.datetime.fromisoformat(value)

class RegistryRecordStore(RegistryTopicStore):
    def initialize(self):
        if not (self.engine.url.database or '').startswith('kdbt_registry_candidate_'):raise ValueError('Isolated record candidate required')
        super().initialize();metadata.create_all(self.engine)
        with self.engine.begin() as c:c.execute(text('ALTER TABLE console_record_snapshots ADD COLUMN IF NOT EXISTS json_null_fields JSONB'))
        for index in records.indexes:index.create(self.engine,checkfirst=True)
    @cached_property
    def record_interfaces(self):return json.loads(Path(__file__).with_name('registry_record_contract.json').read_text())
    def record_contracts(self):return self.record_interfaces
    def record_interface(self,definition):return self.record_contracts().get(definition['register_purpose']+':'+definition['register_mnemonic'])
    def snapshot_values(self,register,kind,original,json_null_fields=None):
        contract=next(value for value in self.record_contracts().values() if value['register_id']==register)
        value=json.loads(original);key=hashlib.sha256(json.dumps([value[name] for name in contract[kind]['primary_key']],sort_keys=True).encode()).hexdigest()
        stamp=lambda field:record_timestamp(value[field]) if value.get(field) else None
        if json_null_fields is None:json_null_fields=[name for name,meta in contract[kind]['columns'].items() if meta['type'] in {'json','jsonb'} and value.get(name) is None]
        return {'kind':kind,'register_id':register,'key':key,'record_id':value.get('internal_record_id'),'link_id':value.get('link_internal_record_id'),'subject_id':value.get('subject_internal_record_id'),'tab_id':value.get('tab_id'),'section_id':value.get('section_id'),'created_at':stamp('created_at'),'approved_at':stamp('approved_at'),'source_json':original,'data':value,'json_null_fields':json_null_fields}
    def insert_snapshots(self,c,values):
        # Cast the original JSON text in PostgreSQL instead of re-encoding a
        # Python float. Both the query projection and raw copy keep precision.
        batch=[]
        for value in values:
            value=dict(value);value.pop('data',None);value['_record_raw']=value['source_json'];batch.append(value)
        if batch:c.execute(insert(records).values(data=cast(bindparam('_record_raw',type_=Text),JSONB)),batch)
    def seed_records(self,dataset):
        with self.engine.begin() as c:
            for register,data in dataset.items():
                for kind,values in data.items():
                    if c.execute(select(records.c.key).where(records.c.kind==kind,records.c.register_id==register).limit(1)).first():raise RuntimeError('Refusing to overwrite record snapshots')
                    batch=[]
                    for original in values:batch.append(self.snapshot_values(register,kind,original))
                    if batch:self.insert_snapshots(c,batch)
    def history_sections(self,c,register,tab):
        link=layouts.alias('history_link');section=layouts.alias('history_section')
        return list(c.execute(select(section.c.data).select_from(section.join(link,link.c.data['section_id'].as_string()==section.c.id)).where(section.c.kind=='section',link.c.kind=='link',section.c.data['register_id'].as_string()==register,link.c.data['register_id'].as_string()==register,link.c.data['tab_id'].as_string()==tab)).scalars())
    def legacy_subject_ids(self,c,section_register,subject_register,subject):
        if section_register==subject_register:return [subject]
        path=[];current=section_register
        for _ in range(20):
            definition=self.definition(c,'register',current)
            if definition is None:return [subject]
            path.append(definition)
            if current==subject_register:break
            current=definition.get('master_register_id')
            if not current:return [subject]
        else:return [subject]
        ids=[subject]
        for definition in reversed(path[:-1]):
            interface=self.record_interface(definition)
            if not interface or not interface.get('current'):raise RegistryError('SYS-ERR-001')
            ids=list(c.execute(select(records.c.record_id).where(records.c.kind=='current',records.c.register_id==definition['register_id'],records.c.link_id.in_(ids))).scalars())
            if not ids:break
        return ids
    def subject_history_query(self,c,section_register,register,subject,tab):
        ids=self.legacy_subject_ids(c,section_register,register,subject)
        condition=records.c.subject_id==subject
        if ids:condition=or_(condition,and_(records.c.subject_id.is_(None),records.c.record_id.in_(ids)))
        elif section_register==register:condition=or_(condition,and_(records.c.subject_id.is_(None),records.c.record_id==subject))
        return select(records.c.data).where(records.c.kind=='history',records.c.register_id==section_register,records.c.tab_id==tab,condition)
    def version_key(self,value):
        if value.get('change_request_id'):return ('cr',value['change_request_id'])
        if value.get('submission_id'):return ('submission',value['submission_id'])
        return None
    def execute_request(self,path,p,actor,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_request(path,p,actor,pagination)
        register=p['register_id'];op=path.rsplit('/',1)[-1]
        with self.engine.connect() as c:
            definition=self.require_definition(c,register)
            if op=='get_schema_definition_for_register_section':
                section=c.execute(select(layouts.c.data).where(layouts.c.kind=='section',layouts.c.id==p['section_id'],layouts.c.data['register_id'].as_string()==register)).scalar_one_or_none()
                # The source references an absent DATA_NOT_FOUND enum member;
                # its public response is the generic system error in this case.
                if section is None:raise RegistryError('SYS-ERR-001')
                value=self.section_wire(c,section);value.update(auto_approval=False,cr_auto_approve_for_intake_form=False,is_primary_section=section['section_register_id']==register,section_order=0)
                return self.models.model('RegisterSectionData').model_validate(value).model_dump(mode='json'),None
            subject=p['internal_record_id'];tab=p['tab_id'];sections=self.history_sections(c,register,tab);history=[];base={'register_id':register,'internal_record_id':subject,'tab_id':tab}
            if op=='get_versions_for_a_date':
                output=[]
                for section in sections:
                    child=self.definition(c,'register',section['section_register_id']);interface=self.record_interface(child) if child else None
                    if not interface or not interface.get('history'):continue
                    stamp=datetime.date.fromisoformat(p['truncated_created_date'])
                    query=self.subject_history_query(c,child['register_id'],register,subject,tab).where(func.date(records.c.created_at)==stamp,records.c.section_id==section['section_id']).order_by(records.c.created_at.desc())
                    versions={}
                    for value in c.execute(query).scalars():
                        key=self.version_key(value)
                        if key and key not in versions:versions[key]={'change_request_id':value.get('change_request_id'),'submission_id':None if value.get('change_request_id') else value.get('submission_id'),'created_at':record_timestamp(value['created_at']).isoformat(),'request_id':None}
                    crids=[value['change_request_id'] for value in versions.values() if value['change_request_id']]
                    request_ids={value['change_request_id']:value.get('awe_request_id') for value in c.execute(select(rows.c.data).where(rows.c.kind=='change',rows.c.data['change_request_id'].astext.in_(crids))).scalars()} if crids else {}
                    for value in versions.values():value['request_id']=request_ids.get(value['change_request_id'])
                    if versions:output.append({**base,'truncated_created_date':p['truncated_created_date'],'section_id':section['section_id'],'section_mnemonic':section['section_mnemonic'],'section_register_id':section['section_register_id'],'changes':list(versions.values())})
                return output,None
            for child_id in {section['section_register_id'] for section in sections}:
                child=self.definition(c,'register',child_id);interface=self.record_interface(child) if child else None
                if interface and interface.get('history'):history.extend(c.execute(self.subject_history_query(c,child_id,register,subject,tab)).scalars())
            if op=='get_version_dates':return {**base,'version_dates':sorted({record_timestamp(value['created_at']).date().isoformat() for value in history if value.get('created_at')},reverse=True)},None
            interface=self.record_interface(definition)
            if not interface or not interface['extension_current_available']:raise RegistryError('SYS-ERR-001')
            current=c.execute(select(records.c.data).where(records.c.kind=='current',records.c.register_id==register,records.c.record_id==subject)).scalar_one_or_none() or {}
            latest=max((value for value in history if value.get('approved_at')),key=lambda value:record_timestamp(value['approved_at']),default={})
            return {**base,'number_of_versions':len({self.version_key(value) for value in history if self.version_key(value)}),'last_updated_by':current.get('last_approved_by'),'last_updated_at':current.get('last_approved_at'),'last_approved_by':latest.get('approved_by'),'last_approved_at':latest.get('approved_at')},None
