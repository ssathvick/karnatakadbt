"""Closed-fence encrypted write capture for the three native administration DBs."""
import hashlib,re
from psycopg2 import sql
from registry_native_write_capture import PublicCaptureAuthorization,identifier

TABLES={
 'iam':{'data_policies','login_providers','staff_application_permissions','staff_portal_applications','staff_role_permissions','staff_roles'},
 'consent':{'audit_logs','auth_contexts','cm_awe_processed_events','consent_artefacts','consent_receipts','consent_requests','decision_logs','partner_policies','partners','revocation_records'},
 'partner':{'pm_audit_events','pm_partner_keys','pm_partner_requests','pm_partners'}}

def install(connection,*,profile,capture_schema,tables,key,authorization):
    if profile not in TABLES or set(tables)!=TABLES[profile]:raise ValueError('Complete administration table allowlist required')
    if not re.fullmatch('kdbt_(?:admin_shadow|acceptance)_'+profile+'_[0-9a-f]+',connection.info.dbname):raise ValueError('Dedicated native administration database required')
    identifier(capture_schema)
    if capture_schema=='public' or connection.autocommit or len(key)<40:raise ValueError('Private capture schema, transaction and recovery key required')
    if not isinstance(authorization,PublicCaptureAuthorization):raise ValueError('Closed-fence capture authorization required')
    authorization.validate(connection,tables)
    with connection.cursor() as c:
        c.execute("SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='pgcrypto'");row=c.fetchone()
        if row is None:
            c.execute('CREATE EXTENSION pgcrypto');c.execute("SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='pgcrypto'");row=c.fetchone()
        crypto=identifier(row[0]);schema=sql.Identifier(capture_schema)
        c.execute(sql.SQL('CREATE SCHEMA {}').format(schema));c.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM PUBLIC').format(schema))
        c.execute(sql.SQL('CREATE TABLE {}.control(singleton boolean PRIMARY KEY CHECK(singleton),key_digest text NOT NULL)').format(schema));c.execute(sql.SQL('INSERT INTO {}.control VALUES(true,%s)').format(schema),(hashlib.sha256(key.encode()).hexdigest(),))
        c.execute(sql.SQL('CREATE TABLE {}.events(sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,transaction_id text NOT NULL,table_name text NOT NULL,operation text NOT NULL,producer text NOT NULL,ciphertext bytea NOT NULL)').format(schema))
        body='''DECLARE secret text; expected text; before_row jsonb; after_row jsonb;
          before_nulls text[] := ARRAY[]::text[]; after_nulls text[] := ARRAY[]::text[]; field text; is_null boolean;
        BEGIN
          IF TG_OP='TRUNCATE' THEN RAISE EXCEPTION USING ERRCODE='55000',MESSAGE='NATIVE_TRUNCATE_REQUIRES_ROW_RECOVERY'; END IF;
          secret:=pg_catalog.current_setting('kdbt.native_capture_key',true);
          SELECT key_digest INTO expected FROM CAPTURE.control WHERE singleton;
          IF secret IS NULL OR expected IS NULL OR pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(secret,'UTF8')),'hex')<>expected THEN
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
          INSERT INTO CAPTURE.events(transaction_id,table_name,operation,producer,ciphertext)
          VALUES(pg_catalog.pg_current_xact_id()::text,TG_TABLE_NAME,TG_OP,
            coalesce(nullif(pg_catalog.current_setting('kdbt.native_capture_writer',true),''),'native-unclassified'),
            CRYPTO.pgp_sym_encrypt(pg_catalog.jsonb_build_object('before',before_row,'after',after_row,
              'before_sql_null_fields',before_nulls,'after_sql_null_fields',after_nulls)::text,secret,'cipher-algo=aes256,compress-algo=1'));
          RETURN NULL;
        END'''.replace('CAPTURE.',schema.as_string(c)+'.').replace('CRYPTO.',sql.Identifier(crypto).as_string(c)+'.')
        c.execute(sql.SQL('CREATE FUNCTION {}.capture() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS {}').format(schema,sql.Literal(body)));c.execute(sql.SQL('REVOKE ALL ON FUNCTION {}.capture() FROM PUBLIC').format(schema))
        for table in sorted(tables):
            c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s AND data_type IN ('json','jsonb') ORDER BY ordinal_position",(table,));columns=[row[0] for row in c.fetchall()]
            c.execute(sql.SQL('CREATE TRIGGER native_recovery_row_capture AFTER INSERT OR UPDATE OR DELETE ON public.{} FOR EACH ROW EXECUTE FUNCTION {}.capture({})').format(sql.Identifier(table),schema,sql.SQL(',').join(map(sql.Literal,columns))))
            c.execute(sql.SQL('CREATE TRIGGER native_recovery_truncate_guard BEFORE TRUNCATE ON public.{} FOR EACH STATEMENT EXECUTE FUNCTION {}.capture()').format(sql.Identifier(table),schema))
    return {'target_tables':len(tables),'crypto_schema':crypto}
