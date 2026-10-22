"""Transactional source journal and idempotent migration mirror.

The mirror is a recovery/staging representation, not the native console's
projection. Source acknowledgements follow destination commit. There is no
sequence high-water mark: transactions that commit late cannot be skipped.
"""
import hashlib
import json
import uuid
from psycopg2 import sql

SCHEMA='kdbt_migration_capture'
TRIGGER='kdbt_registry_capture'


def table_contract(connection, tables=None):
    with connection.cursor() as c:
        c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        available=[row[0] for row in c.fetchall()]
        selected=available if tables is None else list(tables)
        if not selected or set(selected)-set(available):raise ValueError('Explicit existing source tables required')
        result={}
        for table in selected:
            c.execute("SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey) WHERE i.indrelid=%s::regclass AND i.indisprimary ORDER BY array_position(i.indkey,a.attnum)",('public.'+table,))
            keys=[row[0] for row in c.fetchall()]
            if not keys:raise ValueError('Every mirrored table needs a primary key')
            c.execute("SELECT column_name,data_type,udt_name,is_nullable FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",(table,))
            columns=c.fetchall()
            result[table]={'keys':keys,'columns':columns,'json_columns':[row[0] for row in columns if row[1] in {'json','jsonb'}]}
        return result


def install_source(connection, tables=None):
    """Install journal atomically; existing contract drift is rejected."""
    contract=table_contract(connection,tables)
    serialized=json.dumps(contract,sort_keys=True)
    with connection.cursor() as c:
        c.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(SCHEMA)))
        c.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM PUBLIC').format(sql.Identifier(SCHEMA)))
        c.execute(sql.SQL('CREATE TABLE IF NOT EXISTS {}.identity (singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), source_id uuid NOT NULL, contract jsonb NOT NULL)').format(sql.Identifier(SCHEMA)))
        c.execute(sql.SQL('SELECT source_id,contract::text FROM {}.identity WHERE singleton').format(sql.Identifier(SCHEMA)))
        old=c.fetchone()
        if old and json.loads(old[1])!=json.loads(serialized):raise ValueError('Journal table contract changed; explicit migration required')
        if not old:
            c.execute(sql.SQL('INSERT INTO {}.identity(singleton,source_id,contract) VALUES(true,%s,%s::jsonb)').format(sql.Identifier(SCHEMA)),(str(uuid.uuid4()),serialized))
        c.execute(sql.SQL('CREATE TABLE IF NOT EXISTS {}.events (event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, transaction_id bigint NOT NULL, table_name text NOT NULL, operation text NOT NULL, before_row jsonb, after_row jsonb, sql_null_fields text[] NOT NULL, acknowledged boolean NOT NULL DEFAULT false)').format(sql.Identifier(SCHEMA)))
        c.execute(sql.SQL('CREATE INDEX IF NOT EXISTS kdbt_capture_unacknowledged ON {}.events(transaction_id,event_id) WHERE NOT acknowledged').format(sql.Identifier(SCHEMA)))
        # Fixed identifiers and search_path; the application role gets no direct
        # journal access merely because it can mutate its business tables.
        c.execute('''CREATE OR REPLACE FUNCTION kdbt_migration_capture.capture() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE old_value jsonb; new_value jsonb; nulls text[] := ARRAY[]::text[];
        field text; is_null boolean;
BEGIN
  IF TG_OP <> 'INSERT' AND TG_OP <> 'TRUNCATE' THEN old_value := to_jsonb(OLD); END IF;
  IF TG_OP <> 'DELETE' AND TG_OP <> 'TRUNCATE' THEN
    new_value := to_jsonb(NEW);
    FOREACH field IN ARRAY string_to_array(TG_ARGV[0], ',') LOOP
      IF field <> '' THEN
        EXECUTE format('SELECT ($1).%I IS NULL', field) INTO is_null USING NEW;
        IF is_null THEN nulls := array_append(nulls,field); END IF;
      END IF;
    END LOOP;
  END IF;
  INSERT INTO kdbt_migration_capture.events(transaction_id,table_name,operation,before_row,after_row,sql_null_fields)
    VALUES(txid_current(),TG_TABLE_NAME,TG_OP,old_value,new_value,nulls);
  RETURN NULL;
END $$''')
        c.execute('REVOKE ALL ON FUNCTION kdbt_migration_capture.capture() FROM PUBLIC')
        for table,meta in contract.items():
            for name in [TRIGGER,TRIGGER+'_truncate']:
                c.execute(sql.SQL('DROP TRIGGER IF EXISTS {} ON public.{}').format(sql.Identifier(name),sql.Identifier(table)))
            c.execute(sql.SQL('CREATE TRIGGER {} AFTER INSERT OR UPDATE OR DELETE ON public.{} FOR EACH ROW EXECUTE FUNCTION {}.capture({})').format(sql.Identifier(TRIGGER),sql.Identifier(table),sql.Identifier(SCHEMA),sql.Literal(','.join(meta['json_columns']))))
            c.execute(sql.SQL('CREATE TRIGGER {} AFTER TRUNCATE ON public.{} FOR EACH STATEMENT EXECUTE FUNCTION {}.capture({})').format(sql.Identifier(TRIGGER+'_truncate'),sql.Identifier(table),sql.Identifier(SCHEMA),sql.Literal('')))
    return contract


def initialize_mirror(connection, schema):
    with connection.cursor() as c:
        c.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(schema)))
        c.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM PUBLIC').format(sql.Identifier(schema)))
        c.execute(sql.SQL('CREATE TABLE IF NOT EXISTS {}.state (source_id uuid PRIMARY KEY, baseline_snapshot text NOT NULL, contract jsonb NOT NULL)').format(sql.Identifier(schema)))
        c.execute(sql.SQL('CREATE TABLE IF NOT EXISTS {}.rows (source_id uuid NOT NULL,table_name text NOT NULL,row_key jsonb NOT NULL,data jsonb NOT NULL,sql_null_fields text[] NOT NULL,PRIMARY KEY(source_id,table_name,row_key))').format(sql.Identifier(schema)))
        c.execute(sql.SQL('CREATE TABLE IF NOT EXISTS {}.receipts (source_id uuid NOT NULL,event_id bigint NOT NULL,transaction_id bigint NOT NULL,digest text NOT NULL,PRIMARY KEY(source_id,event_id))').format(sql.Identifier(schema)))


def source_identity(connection):
    with connection.cursor() as c:
        c.execute(sql.SQL('SELECT source_id::text,contract FROM {}.identity WHERE singleton').format(sql.Identifier(SCHEMA)))
        row=c.fetchone()
    if row is None:raise ValueError('Source journal is not installed')
    return row


def _key_expression(keys):
    # The source PostgreSQL JSONB parser, not a Python float conversion, owns
    # decimal values and canonical JSON primary-key representation.
    return sql.SQL('jsonb_build_object({})').format(sql.SQL(',').join(
        sql.SQL('{}, value -> {}').format(sql.Literal(key),sql.Literal(key)) for key in keys))


def put_mirror_row(c,schema,source,table,keys,raw,nulls):
    c.execute(sql.SQL('WITH v AS (SELECT %s::jsonb AS value) INSERT INTO {}.rows SELECT %s,%s,{},value,%s::text[] FROM v ON CONFLICT(source_id,table_name,row_key) DO UPDATE SET data=excluded.data,sql_null_fields=excluded.sql_null_fields').format(sql.Identifier(schema),_key_expression(keys)),(raw,source,table,nulls))


def delete_mirror_row(c,schema,source,table,keys,raw):
    c.execute(sql.SQL('WITH v AS (SELECT %s::jsonb AS value) DELETE FROM {}.rows WHERE source_id=%s AND table_name=%s AND row_key=(SELECT {} FROM v)').format(sql.Identifier(schema),_key_expression(keys)),(raw,source,table))


def seed_mirror(source,destination,schema):
    """Caller holds REPEATABLE READ; seed and snapshot identity commit together."""
    identity,contract=source_identity(source)
    with source.cursor() as c,destination.cursor() as d:
        d.execute(sql.SQL('SELECT 1 FROM {}.state WHERE source_id=%s').format(sql.Identifier(schema)),(identity,))
        if d.fetchone():raise ValueError('Mirror already seeded; replay instead of replacing native state')
        c.execute('SELECT txid_current_snapshot()::text');snapshot=c.fetchone()[0]
        count=0
        for table,meta in contract.items():
            nulls=sql.SQL('ARRAY[{}]::text[]').format(sql.SQL(',').join(sql.SQL('CASE WHEN t.{} IS NULL THEN {} END').format(sql.Identifier(field),sql.Literal(field)) for field in meta['json_columns']))
            c.execute(sql.SQL('SELECT to_jsonb(t)::text,array_remove({},NULL) FROM public.{} t').format(nulls,sql.Identifier(table)))
            while True:
                batch=c.fetchmany(1000)
                if not batch:break
                for raw,flags in batch:put_mirror_row(d,schema,identity,table,meta['keys'],raw,flags);count+=1
        d.execute(sql.SQL('INSERT INTO {}.state VALUES(%s,%s,%s::jsonb)').format(sql.Identifier(schema)),(identity,snapshot,json.dumps(contract)))
    return {'tables':len(contract),'rows':count}


def reconcile_receipts(source,destination,schema):
    """Recover delivery after restoring an older destination database backup.

    Source acknowledgements alone cannot prove that a restored destination
    still contains its receipts. Compare the actual receipt set, including gaps
    below its largest event ID, and make missing events eligible for replay.
    """
    identity,_=source_identity(source)
    with source.cursor() as c,destination.cursor() as d:
        c.execute("SELECT pg_advisory_xact_lock(hashtextextended('kdbt-registry-mirror-consumer',0))")
        c.execute('CREATE TEMP TABLE kdbt_receipt_recovery(event_id bigint PRIMARY KEY) ON COMMIT DROP')
        d.execute(sql.SQL('SELECT 1 FROM {}.state WHERE source_id=%s').format(sql.Identifier(schema)),(identity,))
        if not d.fetchone():raise ValueError('Matching mirror baseline required before receipt recovery')
        d.execute(sql.SQL('SELECT event_id FROM {}.receipts WHERE source_id=%s ORDER BY event_id').format(sql.Identifier(schema)),(identity,))
        while True:
            batch=d.fetchmany(1000)
            if not batch:break
            c.executemany('INSERT INTO kdbt_receipt_recovery VALUES(%s)',batch)
        c.execute(sql.SQL('UPDATE {}.events e SET acknowledged=false WHERE acknowledged AND NOT EXISTS(SELECT 1 FROM kdbt_receipt_recovery r WHERE r.event_id=e.event_id)').format(sql.Identifier(SCHEMA)))
        recovered=c.rowcount
    source.commit();destination.commit()
    return {'requeued_events':recovered}


def replay_batch(source,destination,schema, *, before_ack=None, project_event=None):
    """Apply one committed source transaction atomically, then acknowledge it.

    The source connection must use READ COMMITTED and be dedicated to this
    synchronizer. Row locks serialize competing consumers of the same source.
    Exceptions require the caller to roll back both connections before retry.
    """
    identity,contract=source_identity(source)
    with source.cursor() as c,destination.cursor() as d:
        d.execute(sql.SQL('SELECT baseline_snapshot FROM {}.state WHERE source_id=%s').format(sql.Identifier(schema)),(identity,))
        state=d.fetchone()
        if not state:raise ValueError('Consistent baseline required')
        # SKIP LOCKED alone can split one transaction across consumers. A
        # transaction-scoped advisory leader serializes entire transaction groups.
        c.execute("SELECT pg_try_advisory_xact_lock(hashtextextended('kdbt-registry-mirror-consumer',0))")
        if not c.fetchone()[0]:return {'events':0,'standby':True}
        c.execute(sql.SQL('SELECT transaction_id FROM {}.events WHERE NOT acknowledged ORDER BY event_id LIMIT 1 FOR UPDATE').format(sql.Identifier(SCHEMA)))
        first=c.fetchone()
        if not first:return {'events':0}
        tx=first[0]
        c.execute(sql.SQL('SELECT event_id,table_name,operation,before_row::text,after_row::text,sql_null_fields,txid_visible_in_snapshot(transaction_id,%s::txid_snapshot) FROM {}.events WHERE transaction_id=%s AND NOT acknowledged ORDER BY event_id FOR UPDATE').format(sql.Identifier(SCHEMA)),(state[0],tx))
        events=c.fetchall()
        for event_id,table,operation,before,after,nulls,baseline in events:
            digest=hashlib.sha256(json.dumps([table,operation,before,after,nulls],separators=(',',':')).encode()).hexdigest()
            d.execute(sql.SQL('SELECT digest FROM {}.receipts WHERE source_id=%s AND event_id=%s').format(sql.Identifier(schema)),(identity,event_id))
            receipt=d.fetchone()
            if receipt:
                if receipt[0]!=digest:raise ValueError('Source event changed after destination commit')
                continue
            if table not in contract:raise ValueError('Unrecognized journal table')
            if not baseline:
                if operation=='TRUNCATE':
                    d.execute(sql.SQL('DELETE FROM {}.rows WHERE source_id=%s AND table_name=%s').format(sql.Identifier(schema)),(identity,table))
                else:
                    if before is not None:delete_mirror_row(d,schema,identity,table,contract[table]['keys'],before)
                    if after is not None:put_mirror_row(d,schema,identity,table,contract[table]['keys'],after,nulls)
                if project_event:project_event(d,table,operation,before,after,nulls)
            d.execute(sql.SQL('INSERT INTO {}.receipts VALUES(%s,%s,%s,%s)').format(sql.Identifier(schema)),(identity,event_id,tx,digest))
        destination.commit()
        if before_ack:before_ack()
        c.execute(sql.SQL('UPDATE {}.events SET acknowledged=true WHERE transaction_id=%s AND NOT acknowledged').format(sql.Identifier(SCHEMA)),(tx,))
        source.commit()
        return {'events':len(events)}
