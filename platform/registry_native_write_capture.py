"""Atomic encrypted native SQL row capture for API and worker recovery.

Raw native images complement source-schema reverse batches. They do not by
themselves certify legacy replay, external effects or production ownership.
"""
import hashlib,re
from psycopg2 import sql
from sqlalchemy import event

def identifier(value):
    if not re.fullmatch('[a-z_][a-z0-9_]{0,62}',value):raise ValueError('Explicit SQL identifier required')
    return value

class PublicCaptureAuthorization:
    def __init__(self,connection,*,expected_identity,owner,generation,tables):
        if connection.autocommit or not owner or type(generation) is not int:raise ValueError('Transactional native fence authorization required')
        with connection.cursor() as c:
            c.execute('SELECT current_database(),(SELECT oid::text FROM pg_database WHERE datname=current_database()),system_identifier::text FROM pg_control_system()');name,oid,system=c.fetchone()
            if {'database':name,'database_oid':oid,'system_identifier':system}!=expected_identity:raise ValueError('Public capture database identity changed')
            c.execute('SELECT generation,owner,fenced FROM kdbt_migration_fence.control WHERE singleton FOR SHARE');state=c.fetchone()
            if state!=(generation,owner,True):raise ValueError('Public capture installation requires the expected closed native producer fence')
            c.execute('SELECT pg_current_xact_id()::text');self.transaction=c.fetchone()[0]
        self.connection=connection;self.tables=frozenset(tables)
    def validate(self,connection,tables):
        if connection is not self.connection or frozenset(tables)!=self.tables:raise ValueError('Capture authorization scope changed')
        with connection.cursor() as c:c.execute('SELECT pg_current_xact_id()::text');current=c.fetchone()[0]
        if current!=self.transaction:raise ValueError('Capture installation authorization expired with its transaction')

def install(connection,*,capture_schema,target_schema,tables,key,production_authorization=None):
    identifier(capture_schema);identifier(target_schema)
    if not connection.info.dbname.startswith('kdbt_registry_candidate_') or capture_schema=='public':raise ValueError('Dedicated native database and private capture schema required')
    if target_schema=='public':
        if not isinstance(production_authorization,PublicCaptureAuthorization):raise ValueError('Public native capture requires closed-fence authorization')
        production_authorization.validate(connection,tables)
    if connection.autocommit or not tables or len(key)<40:raise ValueError('Transactional capture installation and recovery key required')
    with connection.cursor() as c:
        c.execute('SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname=\'pgcrypto\'')
        row=c.fetchone()
        if row is None:
            c.execute('CREATE EXTENSION IF NOT EXISTS pgcrypto');c.execute('SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname=\'pgcrypto\'');row=c.fetchone()
        crypto=identifier(row[0])
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(capture_schema)))
        c.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM PUBLIC').format(sql.Identifier(capture_schema)))
        c.execute(sql.SQL('CREATE TABLE {}.control(singleton boolean PRIMARY KEY CHECK(singleton),key_digest text NOT NULL)').format(sql.Identifier(capture_schema)))
        c.execute(sql.SQL('INSERT INTO {}.control VALUES(true,%s)').format(sql.Identifier(capture_schema)),(hashlib.sha256(key.encode()).hexdigest(),))
        c.execute(sql.SQL("CREATE TABLE {}.events(sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,transaction_id text NOT NULL,table_name text NOT NULL,operation text NOT NULL,producer text NOT NULL,ciphertext bytea NOT NULL)").format(sql.Identifier(capture_schema)))
        # No secrets occur in the function definition or its arguments. The
        # caller supplies the key transaction-locally; its digest pins identity.
        body='''DECLARE
          secret text; expected text; frame jsonb; before_row jsonb; after_row jsonb;
          before_nulls text[] := ARRAY[]::text[]; after_nulls text[] := ARRAY[]::text[];
          field text; is_null boolean;
        BEGIN
          IF TG_OP='TRUNCATE' THEN
            RAISE EXCEPTION USING ERRCODE='55000',MESSAGE='NATIVE_TRUNCATE_REQUIRES_ROW_RECOVERY';
          END IF;
          secret:=pg_catalog.current_setting('kdbt.native_capture_key',true);
          SELECT key_digest INTO expected FROM CAPTURE.control WHERE singleton;
          IF secret IS NULL OR expected IS NULL OR
            pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(secret,'UTF8')),'hex')<>expected THEN
            RAISE EXCEPTION USING ERRCODE='55000',MESSAGE='NATIVE_RECOVERY_CAPTURE_KEY_UNAVAILABLE';
          END IF;
          IF TG_OP<>'INSERT' THEN before_row:=pg_catalog.to_jsonb(OLD); END IF;
          IF TG_OP<>'DELETE' THEN after_row:=pg_catalog.to_jsonb(NEW); END IF;
          FOREACH field IN ARRAY coalesce(TG_ARGV,ARRAY[]::text[]) LOOP
            IF TG_OP<>'INSERT' THEN
              EXECUTE pg_catalog.format('SELECT ($1).%I IS NULL',field) INTO is_null USING OLD;
              IF is_null THEN before_nulls:=pg_catalog.array_append(before_nulls,field); END IF;
            END IF;
            IF TG_OP<>'DELETE' THEN
              EXECUTE pg_catalog.format('SELECT ($1).%I IS NULL',field) INTO is_null USING NEW;
              IF is_null THEN after_nulls:=pg_catalog.array_append(after_nulls,field); END IF;
            END IF;
          END LOOP;
          IF TG_OP='UPDATE' AND before_row=after_row AND before_nulls=after_nulls THEN RETURN NULL; END IF;
          frame:=pg_catalog.jsonb_build_object('before',before_row,'after',after_row,
            'before_sql_null_fields',before_nulls,'after_sql_null_fields',after_nulls);
          INSERT INTO CAPTURE.events(transaction_id,table_name,operation,producer,ciphertext)
            VALUES(pg_catalog.pg_current_xact_id()::text,TG_TABLE_NAME,TG_OP,
              coalesce(nullif(pg_catalog.current_setting('kdbt.native_capture_writer',true),''),'native-unclassified'),
              CRYPTO.pgp_sym_encrypt(frame::text,secret,'cipher-algo=aes256,compress-algo=1'));
          RETURN NULL;
        END'''.replace('CAPTURE',sql.Identifier(capture_schema).as_string(c)).replace('CRYPTO',sql.Identifier(crypto).as_string(c))
        c.execute(sql.SQL('CREATE FUNCTION {}.capture() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS {}').format(sql.Identifier(capture_schema),sql.Literal(body)))
        c.execute(sql.SQL('REVOKE ALL ON FUNCTION {}.capture() FROM PUBLIC').format(sql.Identifier(capture_schema)))
        for table in sorted(set(tables)):
            identifier(table)
            c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND data_type IN ('json','jsonb') ORDER BY ordinal_position",(target_schema,table));columns=[row[0] for row in c.fetchall()]
            c.execute('SELECT to_regclass(%s)',(target_schema+'.'+table,))
            if c.fetchone()[0] is None:raise ValueError('Capture target is absent')
            c.execute(sql.SQL('CREATE TRIGGER native_recovery_row_capture AFTER INSERT OR UPDATE OR DELETE ON {}.{} FOR EACH ROW EXECUTE FUNCTION {}.capture({})').format(sql.Identifier(target_schema),sql.Identifier(table),sql.Identifier(capture_schema),sql.SQL(',').join(map(sql.Literal,columns))))
            c.execute(sql.SQL('CREATE TRIGGER native_recovery_truncate_guard BEFORE TRUNCATE ON {}.{} FOR EACH STATEMENT EXECUTE FUNCTION {}.capture()').format(sql.Identifier(target_schema),sql.Identifier(table),sql.Identifier(capture_schema)))
        return {'target_tables':len(set(tables)),'crypto_schema':crypto}

def bind_engine(engine,key,writer='native-canary'):
    if len(key)<40:raise ValueError('Persistent native capture key required')
    if writer not in {'native-canary','native-api','native-worker','native-portal'}:raise ValueError('Explicit native producer identity required')
    @event.listens_for(engine,'begin')
    def key_for_transaction(connection):
        connection.exec_driver_sql("SELECT set_config('kdbt.native_capture_key',%s,true)",(key,))
        connection.exec_driver_sql("SELECT set_config('kdbt.native_capture_writer',%s,true)",(writer,))

def frames(connection,*,capture_schema,key,crypto_schema='public'):
    identifier(capture_schema);identifier(crypto_schema)
    with connection.cursor() as c:
        c.execute(sql.SQL('SELECT sequence,transaction_id,table_name,operation,{}.pgp_sym_decrypt(ciphertext,%s),producer FROM {}.events ORDER BY sequence').format(sql.Identifier(crypto_schema),sql.Identifier(capture_schema)),(key,))
        # Raw strings preserve exact numeric values until SQL reverse mapping.
        return [{'sequence':row[0],'transaction_id':row[1],'table':row[2],'operation':row[3],'raw':row[4],'producer':row[5]} for row in c.fetchall()]
