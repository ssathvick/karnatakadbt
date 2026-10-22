"""Keep slot capacity and the retained binary's kilobyte capacity consistent."""
import re
from psycopg2 import sql

def install_status_capacity_compatibility(connection, *, schema='certify', fenced):
    if not callable(fenced) or fenced() is not True:
        raise ValueError('Observed production writer and worker fence required')
    if schema!='certify' and not re.fullmatch('kdbt_status_compat_test_[0-9a-f]{16}',schema):
        raise ValueError('Explicit credential schema required')
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL('LOCK TABLE {}.status_list_credential IN ACCESS EXCLUSIVE MODE').format(sql.Identifier(schema)))
        cursor.execute(sql.SQL('ALTER TABLE {}.status_list_credential ADD COLUMN IF NOT EXISTS capacity_in_kb bigint').format(sql.Identifier(schema)))
        cursor.execute(sql.SQL('''CREATE OR REPLACE FUNCTION {}.kdbt_status_capacity_compatibility() RETURNS trigger
LANGUAGE plpgsql AS $body$
BEGIN
 IF TG_OP='UPDATE' THEN
  IF NEW.capacity IS DISTINCT FROM OLD.capacity AND NEW.capacity_in_kb IS NOT DISTINCT FROM OLD.capacity_in_kb THEN
   NEW.capacity_in_kb := NULL;
  ELSIF NEW.capacity_in_kb IS DISTINCT FROM OLD.capacity_in_kb AND NEW.capacity IS NOT DISTINCT FROM OLD.capacity THEN
   NEW.capacity := NULL;
  END IF;
 END IF;
 IF NEW.capacity IS NULL AND NEW.capacity_in_kb IS NOT NULL THEN
  IF NEW.capacity_in_kb<1 OR NEW.capacity_in_kb>1024 THEN RAISE EXCEPTION 'Unsupported status capacity'; END IF;
  NEW.capacity := NEW.capacity_in_kb*8192;
 ELSIF NEW.capacity_in_kb IS NULL AND NEW.capacity IS NOT NULL THEN
  IF NEW.capacity<8192 OR NEW.capacity>8388608 OR NEW.capacity%8192<>0 THEN RAISE EXCEPTION 'Unsupported status capacity'; END IF;
  NEW.capacity_in_kb := NEW.capacity/8192;
 END IF;
 IF NEW.capacity IS NULL OR NEW.capacity_in_kb IS NULL OR NEW.capacity<>NEW.capacity_in_kb*8192
    OR NEW.capacity_in_kb<1 OR NEW.capacity_in_kb>1024 THEN
  RAISE EXCEPTION 'Conflicting status capacity units';
 END IF;
 NEW.credential_status := COALESCE(NEW.credential_status,'AVAILABLE');
 RETURN NEW;
END $body$''').format(sql.Identifier(schema)))
        cursor.execute(sql.SQL('DROP TRIGGER IF EXISTS kdbt_status_capacity_compatibility ON {}.status_list_credential').format(sql.Identifier(schema)))
        cursor.execute(sql.SQL('''CREATE TRIGGER kdbt_status_capacity_compatibility BEFORE INSERT OR UPDATE ON {}.status_list_credential
FOR EACH ROW EXECUTE FUNCTION {}.kdbt_status_capacity_compatibility()''').format(sql.Identifier(schema),sql.Identifier(schema)))
        cursor.execute(sql.SQL('UPDATE {}.status_list_credential SET capacity=capacity').format(sql.Identifier(schema)))
        cursor.execute(sql.SQL('SELECT count(*) FROM {}.status_list_credential WHERE capacity IS NULL OR capacity_in_kb IS NULL OR capacity<>capacity_in_kb*8192 OR credential_status IS NULL').format(sql.Identifier(schema)))
        if cursor.fetchone()[0]:raise ValueError('Status capacity recovery differs')
    if fenced() is not True:raise ValueError('Writer fence changed before schema commit')

