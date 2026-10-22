"""Encrypted, transaction-bound recovery batches for every registry contract.

Call append on the SAME SQL transaction as native business writes. The caller
must supply complete source-schema images; this module does not infer missing
beneficiary fields or grant production rollback/worker ownership.
"""
import hashlib,json
from cryptography.fernet import Fernet
from sqlalchemy import MetaData,Table,Column,String,Text,select,insert,text
from registry_record_rollback import RecordRollback
from registry_metadata_rollback import MetadataRollback
from registry_queue_rollback import QueueRollback
from registry_remaining_rollback import RemainingRegistryRollback

metadata=MetaData()
batches=Table('native_registry_reverse_batches',metadata,Column('operation_id',String,primary_key=True),Column('writer',String,nullable=False),Column('contract_digest',String,nullable=False),Column('digest',String,nullable=False),Column('ciphertext',Text,nullable=False))

class FullRegistryRollback(RecordRollback):
    def __init__(self,source_contract):
        self.mapping={}
        for adapter in [RecordRollback(),MetadataRollback(source_contract),QueueRollback(source_contract),RemainingRegistryRollback(source_contract)]:
            for table,profile in adapter.mapping.items():
                if table not in source_contract:raise ValueError('Captured registry source contract incomplete')
                if table in self.mapping:continue
                captured=source_contract[table]
                if set(profile['columns'])!={row[0] for row in captured['columns']} or profile['primary_key']!=captured['keys']:raise ValueError('Reverse contract differs from captured schema')
                if any(profile['columns'][name]['type']!=typ for name,typ,udt,nullable in captured['columns']):raise ValueError('Reverse column types differ from captured schema')
                self.mapping[table]=profile
        if set(self.mapping)!=set(source_contract):raise ValueError('Captured registry contains unsupported reverse tables')

class RegistryReverseJournal:
    def __init__(self,engine,source_contract,encryption_key):
        self.engine=engine;self.recovery=FullRegistryRollback(source_contract);self.cipher=Fernet(encryption_key)
        self.contract_digest=hashlib.sha256(json.dumps(source_contract,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    def initialize(self):metadata.create_all(self.engine)
    def validate(self,changes):
        if not isinstance(changes,list) or not changes:raise ValueError('Explicit reverse change batch required')
        for change in changes:
            if change.get('table') not in self.recovery.mapping:raise ValueError('Unsupported reverse table')
            profile=self.recovery.mapping[change['table']];allowed_nulls={field for field,meta in profile['columns'].items() if meta['type'] in {'json','jsonb'}}
            if change.get('before') is None and change.get('after') is None:raise ValueError('Empty reverse change')
            for side in ['before','after']:
                raw=change.get(side);nulls=change.get(side+'_sql_null_fields',[])
                if not isinstance(nulls,list) or any(not isinstance(field,str) for field in nulls) or len(set(nulls))!=len(nulls) or set(nulls)-allowed_nulls:raise ValueError('Invalid SQL-null recovery metadata')
                if raw is None:
                    if nulls:raise ValueError('Missing row cannot have SQL-null fields')
                    continue
                value=json.loads(raw)
                if not isinstance(value,dict) or set(value)!=set(profile['columns']):raise ValueError('Incomplete source-schema recovery image')
                if any(value[key] is None for key in profile['primary_key']):raise ValueError('Recovery primary key missing')
                if any(value[field] is not None for field in nulls):raise ValueError('SQL-null flag contradicts row value')
            if change.get('before') and change.get('after'):
                before=json.loads(change['before']);after=json.loads(change['after'])
                if any(before[field]!=after[field] for field in profile['primary_key']):raise ValueError('Recovery row identity changed')
    def append(self,connection,operation_id,writer,changes):
        if not connection.in_transaction() or getattr(connection.connection.driver_connection,'autocommit',False):raise ValueError('Business SQL transaction required for recovery capture')
        if not isinstance(operation_id,str) or not operation_id or not isinstance(writer,str) or not writer:raise ValueError('Recovery operation and writer required')
        self.validate(changes);raw=json.dumps(changes,sort_keys=True,separators=(',',':'));digest=hashlib.sha256(raw.encode()).hexdigest()
        connection.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':'native-registry-reverse:'+operation_id})
        prior=connection.execute(select(batches).where(batches.c.operation_id==operation_id)).mappings().first()
        if prior:
            if prior['digest']!=digest or prior['writer']!=writer or prior['contract_digest']!=self.contract_digest:raise ValueError('Recovery operation identifier reused with different business writes')
            return False
        connection.execute(insert(batches).values(operation_id=operation_id,writer=writer,contract_digest=self.contract_digest,digest=digest,ciphertext=self.cipher.encrypt(raw.encode()).decode()));return True
    def read(self,connection,operation_id):
        row=connection.execute(select(batches).where(batches.c.operation_id==operation_id)).mappings().one()
        if row['contract_digest']!=self.contract_digest:raise ValueError('Recovery contract fingerprint changed')
        raw=self.cipher.decrypt(row['ciphertext'].encode())
        if hashlib.sha256(raw).hexdigest()!=row['digest']:raise ValueError('Recovery batch checksum mismatch')
        value=json.loads(raw);self.validate(value);return value
