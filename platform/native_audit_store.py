"""Durable audit admission/outbox and idempotent partitioned event storage."""
import json,re
from datetime import datetime,timezone
from sqlalchemy import text
from native_audit_models import AuditEvent

class AuditQueueFull(Exception):
    def __init__(self,accepted):self.accepted=accepted

def month_offset(value,months):
    index=value.year*12+value.month-1+months
    return datetime(index//12,index%12+1,1,tzinfo=timezone.utc)

class NativeAuditStore:
    def __init__(self,engine,*,schema='public',queue_max_size=10000):
        if not re.fullmatch('[a-z_][a-z0-9_]{0,62}',schema) or queue_max_size<1:raise ValueError('Explicit audit schema and positive queue bound required')
        self.engine,self.schema,self.limit=engine,schema,queue_max_size
        self.prefix='"'+schema+'".'
    def initialize(self):
        with self.engine.begin() as c:
            name=c.execute(text('SELECT current_database()')).scalar_one()
            if self.schema=='public' and not name.startswith('kdbt_audit_candidate_'):raise ValueError('Native audit requires its own database')
            if self.schema!='public' and not self.schema.startswith('audit_accept_'):raise ValueError('Disposable audit schema required')
            c.execute(text('CREATE SCHEMA IF NOT EXISTS "'+self.schema+'"'));c.execute(text('REVOKE ALL ON SCHEMA "'+self.schema+'" FROM PUBLIC'))
            c.execute(text('CREATE TABLE IF NOT EXISTS '+self.prefix+'''audit_events(
                id text NOT NULL,occurred_at timestamptz NOT NULL,ingested_at timestamptz NOT NULL DEFAULT now(),
                source text NOT NULL,type text NOT NULL,subject text,actor_type text NOT NULL,actor_id text NOT NULL,
                resource_type text,resource_id text,action text NOT NULL,outcome text NOT NULL,reason text,trace_id text,
                details jsonb,PRIMARY KEY(id,occurred_at)) PARTITION BY RANGE(occurred_at)'''))
            for name,fields in [('actor','actor_id,occurred_at DESC'),('resource','resource_type,resource_id,occurred_at DESC'),('type','type,occurred_at DESC'),('time','occurred_at DESC'),('trace','trace_id')]:
                c.execute(text('CREATE INDEX IF NOT EXISTS native_audit_'+name+' ON '+self.prefix+'audit_events('+fields+')'))
            c.execute(text('CREATE TABLE IF NOT EXISTS '+self.prefix+'''native_audit_outbox(
                id text NOT NULL,occurred_at timestamptz NOT NULL,event jsonb NOT NULL,accepted_at timestamptz NOT NULL DEFAULT now(),
                published_at timestamptz,PRIMARY KEY(id,occurred_at))'''))
            c.execute(text('ALTER TABLE '+self.prefix+'native_audit_outbox ADD COLUMN IF NOT EXISTS sequence bigint GENERATED ALWAYS AS IDENTITY'))
    def _partition(self,c,stamp):
        start=month_offset(stamp,0);end=month_offset(start,1);name='audit_events_'+start.strftime('%Y_%m')
        c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':'native-audit-partitions:'+self.schema})
        archived='"'+self.schema+'_archive"."'+name+'"'
        if c.execute(text('SELECT to_regclass(:name)'),{'name':archived}).scalar_one() is not None:return archived
        # Names and boundaries are derived exclusively from validated datetimes.
        c.execute(text('CREATE TABLE IF NOT EXISTS '+self.prefix+'"'+name+'" PARTITION OF '+self.prefix+"audit_events FOR VALUES FROM ('"+start.isoformat()+"') TO ('"+end.isoformat()+"')"))
        return self.prefix+'audit_events'
    def maintain(self,*,pre_create_months=3,retention_months=84,now=None):
        if pre_create_months<1 or retention_months<0:raise ValueError('Invalid audit retention settings')
        now=now or datetime.now(timezone.utc);archived=0
        with self.engine.begin() as c:
            for delta in range(pre_create_months):self._partition(c,month_offset(now,delta))
            if retention_months:
                cutoff=month_offset(now,-retention_months);archive=self.schema+'_archive'
                if len(archive)>63:raise ValueError('Audit archive schema name too long')
                c.execute(text('CREATE SCHEMA IF NOT EXISTS "'+archive+'"'));c.execute(text('REVOKE ALL ON SCHEMA "'+archive+'" FROM PUBLIC'))
                children=c.execute(text('SELECT child.relname FROM pg_inherits i JOIN pg_class parent ON parent.oid=i.inhparent JOIN pg_namespace n ON n.oid=parent.relnamespace JOIN pg_class child ON child.oid=i.inhrelid WHERE n.nspname=:schema AND parent.relname=\'audit_events\''),{'schema':self.schema}).scalars().all()
                for child in children:
                    if not re.fullmatch(r'audit_events_\d{4}_\d{2}',child):raise ValueError('Unknown audit partition; retention stopped')
                    if child[-7:]<cutoff.strftime('%Y_%m'):
                        c.execute(text('ALTER TABLE '+self.prefix+'audit_events DETACH PARTITION '+self.prefix+'"'+child+'"'))
                        c.execute(text('ALTER TABLE '+self.prefix+'"'+child+'" SET SCHEMA "'+archive+'"'));archived+=1
        return archived
    def admit(self,events):
        accepted=[];full=False
        with self.engine.begin() as c:
            c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':'native-audit-ingest:'+self.schema})
            pending=c.execute(text('SELECT count(*) FROM '+self.prefix+'native_audit_outbox WHERE published_at IS NULL')).scalar_one()
            for event in events:
                parameters={'id':event.id,'at':event.occurred_at(),'event':event.model_dump_json()}
                exists=c.execute(text('SELECT 1 FROM '+self.prefix+'native_audit_outbox WHERE id=:id AND occurred_at=:at'),parameters).first()
                if exists:accepted.append(event.id);continue
                if pending>=self.limit:full=True;break
                c.execute(text('INSERT INTO '+self.prefix+'native_audit_outbox(id,occurred_at,event) VALUES(:id,:at,CAST(:event AS jsonb))'),parameters);pending+=1;accepted.append(event.id)
        if full:raise AuditQueueFull(accepted)
        return accepted
    async def publish_once(self,send,*,limit=100):
        # One publisher owns this transaction. Kafka acknowledgement precedes
        # SQL receipt; a crash in between produces a harmless duplicate.
        count=0
        with self.engine.begin() as c:
            rows=c.execute(text('SELECT id,occurred_at,event FROM '+self.prefix+'native_audit_outbox WHERE published_at IS NULL ORDER BY sequence FOR UPDATE SKIP LOCKED LIMIT :limit'),{'limit':limit}).mappings().all()
            for row in rows:
                await send(row['event'])
                c.execute(text('UPDATE '+self.prefix+'native_audit_outbox SET published_at=now() WHERE id=:id AND occurred_at=:at'),{'id':row['id'],'at':row['occurred_at']});count+=1
        return count
    def persist(self,events):
        with self.engine.begin() as c:
            targets={month:self._partition(c,month) for month in {month_offset(event.occurred_at(),0) for event in events}}
            for event in events:
                row=event.record();row['details']=json.dumps(row['details']) if row['details'] is not None else None
                fields=list(row);placeholders=['CAST(:details AS jsonb)' if key=='details' else ':'+key for key in fields]
                c.execute(text('INSERT INTO '+targets[month_offset(event.occurred_at(),0)]+'('+','.join(fields)+') VALUES('+','.join(placeholders)+') ON CONFLICT(id,occurred_at) DO NOTHING'),row)
    def healthy(self):
        with self.engine.connect() as c:return c.execute(text('SELECT 1')).scalar_one()==1
