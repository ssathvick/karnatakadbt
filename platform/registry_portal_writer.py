"""Native portal projections with atomic before/after recovery receipts.

Production admission requires a completed forward handoff locked for this
transaction. Rehearsals are restricted to explicitly named isolated schemas.
"""
import datetime,hashlib,json
from sqlalchemy import MetaData,Table,Column,String,DateTime,select,insert,update,text,func,cast,Text
from sqlalchemy.dialects.postgresql import JSONB
from native_worker_handoff import handoffs
from registry_record_store import records,record_timestamp
from registry_definition_store import states

metadata=MetaData()
writes=Table('native_portal_registry_writes',metadata,Column('operation_id',String,primary_key=True),Column('digest',String,nullable=False),Column('reference',String,nullable=False),Column('version',String,nullable=False),Column('changes',JSONB,nullable=False),Column('at',DateTime,nullable=False))
heads=Table('native_portal_registry_heads',metadata,Column('reference',String,primary_key=True),Column('version',String,nullable=False),Column('digest',String,nullable=False))


class NativePortalRegistryWriter:
    def __init__(self,store,*,scope='registry',rehearsal_schema=None,reverse_journal=None):
        self.store,self.scope,self.rehearsal_schema=store,scope,rehearsal_schema
        self.reverse_journal=reverse_journal
        if rehearsal_schema is not None and not rehearsal_schema.startswith('native_portal_writer_test_'):raise ValueError('Explicit isolated writer schema required')

    def initialize(self):
        metadata.create_all(self.store.engine)
        if self.reverse_journal:self.reverse_journal.initialize()

    def project(self,r,p):
        from registry_portal_payloads import build
        by_table={profile['current']['source_table']:profile['register_id'] for profile in self.store.record_contracts().values() if profile.get('current')}
        patches=[(by_table[table],value) for table,value in build(r,p)]
        digest=hashlib.sha256(json.dumps({'data':json.loads(p['data']),'reference':p['household_ref'],'version':p['updated']},sort_keys=True).encode()).hexdigest()
        return self.apply(operation_id='portal:'+p['household_ref']+':'+p['updated'],reference=p['household_ref'],version=p['updated'],payload_digest=digest,patches=patches)

    def authorize(self,c):
        if self.rehearsal_schema is not None:
            if c.execute(text('SELECT current_schema()')).scalar_one()!=self.rehearsal_schema:raise ValueError('Writer rehearsal cannot target public business state')
            return
        if self.reverse_journal is None:raise ValueError('Production portal writer requires transaction-bound encrypted reverse capture')
        value=c.execute(select(handoffs).where(handoffs.c.scope==self.scope).with_for_update(read=True)).mappings().first()
        if not value or value['direction']!='forward' or value['state']!='COMPLETE' or value['phase']!='release_native_producers':raise ValueError('Native portal writer requires completed fenced handoff')

    def apply(self,*,operation_id,reference,version,payload_digest,patches):
        if not all(isinstance(v,str) and v for v in [operation_id,reference,version,payload_digest]) or not patches:raise ValueError('Explicit versioned portal operation required')
        source_time=record_timestamp(version)
        if source_time.tzinfo is None:source_time=source_time.replace(tzinfo=datetime.timezone.utc)
        version=source_time.astimezone(datetime.timezone.utc).isoformat(timespec='microseconds')
        with self.store.engine.begin() as c:
            self.authorize(c)
            c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':'native-portal-registry:'+reference})
            prior=c.execute(select(writes).where(writes.c.operation_id==operation_id)).mappings().first()
            if prior:
                if prior['digest']!=payload_digest or prior['reference']!=reference or prior['version']!=version:raise ValueError('Portal operation was reused with changed content')
                if self.reverse_journal:self.reverse_journal.append(c,operation_id,'native-portal',prior['changes'])
                return {'skipped':True,'changes':prior['changes']}
            head=c.execute(select(heads).where(heads.c.reference==reference).with_for_update()).mappings().first()
            if head and version<=head['version']:raise ValueError('Stale portal source version')
            changes=[]
            for register,patch in patches:
                definition=self.store.require_definition(c,register);interface=self.store.record_interface(definition)['current'];key=patch['internal_record_id']
                if set(patch)-set(interface['columns']):raise ValueError('Portal patch contains unsupported registry fields')
                before=c.execute(select(cast(records.c.data,Text),records.c.json_null_fields).where(records.c.kind=='current',records.c.register_id==register,records.c.record_id==key).with_for_update()).first()
                existing=self.store.approval_record(c,definition,key) if before else None
                value=dict(existing) if existing is not None else self.store.approval_defaults(self.store.approval_contract['models']['G2PRegister'+definition['register_mnemonic']])
                value.update(patch)
                for field,meta in interface['columns'].items():
                    if meta['type'].startswith('timestamp') and value.get(field) is not None:
                        stamp=record_timestamp(value[field]) if isinstance(value[field],str) else value[field]
                        if meta['type']=='timestamp without time zone' and stamp.tzinfo is not None:stamp=stamp.astimezone(datetime.timezone.utc).replace(tzinfo=None)
                        value[field]=stamp.isoformat()
                nulls=[field for field,meta in interface['columns'].items() if meta['type'] in {'json','jsonb'} and value.get(field) is None] if before is None else None
                self.store.save_register_snapshot(c,definition,'current',value,new=before is None,existing=existing,sql_null_fields=nulls)
                after=c.execute(select(cast(records.c.data,Text),records.c.json_null_fields).where(records.c.kind=='current',records.c.register_id==register,records.c.record_id==key)).one()
                changes.append({'table':interface['source_table'],'before':before[0] if before else None,'before_sql_null_fields':before[1] or [] if before else [],'after':after[0],'after_sql_null_fields':after[1] or []})
                # Update occupancy without replacing fields or schema settings.
                c.execute(update(states).where(states.c.id==register).values(data=func.jsonb_set(cast(states.c.data,JSONB),'{has_data}',cast('true',JSONB))))
            c.execute(insert(writes).values(operation_id=operation_id,digest=payload_digest,reference=reference,version=version,changes=changes,at=self.store.clock().replace(tzinfo=None)))
            if self.reverse_journal:self.reverse_journal.append(c,operation_id,'native-portal',changes)
            if head:c.execute(update(heads).where(heads.c.reference==reference).values(version=version,digest=payload_digest))
            else:c.execute(insert(heads).values(reference=reference,version=version,digest=payload_digest))
            return {'skipped':False,'changes':changes}
