"""Own exact draft/intake domain rows, independent of the registry models."""
import hashlib,json,uuid
from functools import cached_property
from pathlib import Path
from sqlalchemy import MetaData,Table,Column,String,Text,BigInteger,Identity,Index,insert,cast,bindparam
from sqlalchemy.dialects.postgresql import JSONB
from registry_registrant_view_store import RegistryRegistrantViewStore

metadata=MetaData()
intake_records=Table('console_intake_snapshots',metadata,Column('register_id',String,primary_key=True),Column('key',String,primary_key=True),Column('submission_id',String,nullable=False),Column('record_id',String),Column('link_id',String),Column('section_id',String),Column('position',BigInteger,Identity(),nullable=False),Column('source_json',Text,nullable=False),Column('data',JSONB,nullable=False),Column('json_null_fields',JSONB,nullable=False))
Index('ix_console_intake_submission_section',intake_records.c.register_id,intake_records.c.submission_id,intake_records.c.section_id)
Index('ix_console_intake_record',intake_records.c.register_id,intake_records.c.record_id)
Index('ix_console_intake_submission',intake_records.c.submission_id)

class RegistryIntakeRecordStore(RegistryRegistrantViewStore):
    def initialize(self):super().initialize();metadata.create_all(self.engine)
    @cached_property
    def intake_contract(self):return json.loads(Path(__file__).with_name('registry_intake_record_contract.json').read_text())
    def intake_snapshot_values(self,register,original,null_fields=None):
        meta=self.intake_contract[register];value=json.loads(original);key=hashlib.sha256(json.dumps([value[name] for name in meta['primary_key']],sort_keys=True).encode()).hexdigest()
        if null_fields is None:null_fields=[name for name,column in meta['columns'].items() if column['type'] in {'json','jsonb'} and value.get(name) is None]
        return {'register_id':register,'key':key,'submission_id':str(uuid.UUID(value['submission_id'])),'record_id':value.get('internal_record_id'),'link_id':value.get('link_internal_record_id'),'section_id':value.get('section_id'),'source_json':original,'json_null_fields':null_fields}
    def insert_intake_snapshots(self,c,values):
        values=[{**value,'_raw_intake_json':value['source_json']} for value in values]
        if values:c.execute(insert(intake_records).values(data=cast(bindparam('_raw_intake_json',type_=Text),JSONB)),values)
