"""Transactional database fence for every captured registry SQL producer.

Statement triggers acquire shared transaction locks before any business DML.
Changing fence state acquires the matching exclusive lock, waiting for admitted
writes to commit or roll back. Closed admission survives process death.
"""
import hashlib
from psycopg2 import sql

SCHEMA='kdbt_migration_fence'
LOCK='karnatakadbt:registry-producers:v1'


def install(connection,tables,*,capability):
    if connection.autocommit or not tables or len(capability)<40:raise ValueError('Transactional fence installation and private capability required')
    with connection.cursor() as c:
        c.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(SCHEMA)))
        c.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM PUBLIC').format(sql.Identifier(SCHEMA)))
        c.execute(sql.SQL('CREATE TABLE IF NOT EXISTS {}.control(singleton boolean PRIMARY KEY CHECK(singleton),generation bigint NOT NULL,owner text NOT NULL,fenced boolean NOT NULL,capability_hash text NOT NULL)').format(sql.Identifier(SCHEMA)))
        c.execute(sql.SQL('INSERT INTO {}.control VALUES(true,0,\'initial\',false,%s) ON CONFLICT DO NOTHING').format(sql.Identifier(SCHEMA)),(hashlib.sha256(capability.encode()).hexdigest(),))
        c.execute(sql.SQL('SELECT capability_hash FROM {}.control WHERE singleton').format(sql.Identifier(SCHEMA)))
        if c.fetchone()[0]!=hashlib.sha256(capability.encode()).hexdigest():raise ValueError('Existing fence capability differs; preserve original recovery settings')
        # Capability hashes are compared with PostgreSQL's built-in sha256;
        # no extension or developer/application database role is trusted.
        body="""BEGIN
        PERFORM pg_catalog.pg_advisory_xact_lock_shared(pg_catalog.hashtextextended('karnatakadbt:registry-producers:v1',0));
        IF NOT EXISTS(SELECT 1 FROM kdbt_migration_fence.control WHERE singleton) THEN
          RAISE EXCEPTION USING ERRCODE='55000',MESSAGE='KDBT_REGISTRY_FENCE_STATE_UNAVAILABLE';
        END IF;
        IF EXISTS(SELECT 1 FROM kdbt_migration_fence.control WHERE singleton AND fenced
           AND capability_hash<>pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(coalesce(pg_catalog.current_setting('kdbt_migration.fence_capability',true),''),'UTF8')),'hex')) THEN
          RAISE EXCEPTION USING ERRCODE='55000',MESSAGE='KDBT_REGISTRY_PRODUCERS_FENCED';
        END IF;
        RETURN NULL;
        END"""
        c.execute(sql.SQL('CREATE OR REPLACE FUNCTION {}.guard_write() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS {}').format(sql.Identifier(SCHEMA),sql.Literal(body)))
        c.execute(sql.SQL('REVOKE ALL ON FUNCTION {}.guard_write() FROM PUBLIC').format(sql.Identifier(SCHEMA)))
        for table in sorted(tables):
            c.execute('SELECT 1 FROM pg_trigger WHERE tgrelid=%s::regclass AND tgname=%s AND NOT tgisinternal',('public.'+table,'kdbt_producer_fence'))
            if c.fetchone() is None:c.execute(sql.SQL('CREATE TRIGGER kdbt_producer_fence BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.{} FOR EACH STATEMENT EXECUTE FUNCTION {}.guard_write()').format(sql.Identifier(table),sql.Identifier(SCHEMA)))


def state(connection):
    with connection.cursor() as c:
        c.execute(sql.SQL('SELECT generation,owner,fenced FROM {}.control WHERE singleton').format(sql.Identifier(SCHEMA)))
        generation,owner,fenced=c.fetchone();return {'generation':generation,'owner':owner,'fenced':fenced}


def transition(connection,*,generation,owner,fenced):
    if connection.autocommit or type(generation) is not int or generation<1 or not owner or type(fenced) is not bool:raise ValueError('Explicit transactional fence generation required')
    with connection.cursor() as c:
        c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(LOCK,))
        current=state(connection)
        if generation<current['generation'] or (generation==current['generation'] and owner!=current['owner']):raise ValueError('Stale or conflicting producer fence owner')
        if generation>current['generation'] and current['fenced']:raise ValueError('Existing producer fence must be reconciled by its owner')
        c.execute(sql.SQL('UPDATE {}.control SET generation=%s,owner=%s,fenced=%s WHERE singleton').format(sql.Identifier(SCHEMA)),(generation,owner,fenced))


def authorize_recovery(connection,capability):
    if connection.autocommit:raise ValueError('Recovery capability must be transaction-local')
    with connection.cursor() as c:c.execute("SELECT set_config('kdbt_migration.fence_capability',%s,true)",(capability,))
