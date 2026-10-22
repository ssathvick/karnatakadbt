"""Transactional reverse projection of native records into a recovery clone.

Production targets are deliberately rejected until a separately verified,
fenced registry cutover supplies production rollback authorization and routing.
"""
import hashlib,json
from pathlib import Path
from psycopg2 import sql

class RecordRollback:
    def __init__(self,contracts=None):
        self.mapping={}
        contracts=contracts or json.loads(Path(__file__).with_name('registry_record_contract.json').read_text())
        for interface in contracts.values():
            for kind in ['current','history']:
                if interface.get(kind):self.mapping[interface[kind]['source_table']]=interface[kind]

    def lookup(self,c,table,raw):
        profile=self.mapping[table];value=json.loads(raw)
        keys=profile['primary_key']
        predicate=sql.SQL(' AND ').join(sql.SQL('{}=%s').format(sql.Identifier(key)) for key in keys)
        nulls=sql.SQL('ARRAY[{}]::text[]').format(sql.SQL(',').join(sql.SQL('CASE WHEN t.{} IS NULL THEN {} END').format(sql.Identifier(field),sql.Literal(field)) for field,meta in profile['columns'].items() if meta['type'] in {'json','jsonb'}))
        c.execute(sql.SQL('SELECT to_jsonb(t)::text,array_remove({},NULL) FROM public.{} t WHERE {} FOR UPDATE').format(nulls,sql.Identifier(table),predicate),[value[key] for key in keys])
        return c.fetchone(),predicate,[value[key] for key in keys]

    def apply(self,connection,operation_id,changes):
        if connection.autocommit:raise ValueError('Transactional recovery connection required')
        if not connection.info.dbname.startswith('kdbt_registry_ref_'):
            raise ValueError('Rollback rehearsal requires an isolated legacy-schema database')
        return self._apply_transaction(connection,operation_id,changes)

    def _apply_transaction(self,connection,operation_id,changes):
        # Internal primitive. Public clone admission remains above; production
        # callers must use the separately fenced recovery coordinator.
        if not operation_id or not changes:raise ValueError('Explicit recovery operation and changes required')
        digest=hashlib.sha256(json.dumps(changes,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with connection.cursor() as c:
            c.execute('CREATE SCHEMA IF NOT EXISTS kdbt_native_rollback')
            c.execute('REVOKE ALL ON SCHEMA kdbt_native_rollback FROM PUBLIC')
            c.execute('CREATE TABLE IF NOT EXISTS kdbt_native_rollback.receipts(operation_id text PRIMARY KEY,digest text NOT NULL)')
            c.execute("SELECT pg_advisory_xact_lock(hashtextextended('kdbt-record-rollback',0))")
            c.execute('SELECT digest FROM kdbt_native_rollback.receipts WHERE operation_id=%s',(operation_id,))
            receipt=c.fetchone()
            if receipt:
                if receipt[0]!=digest:raise ValueError('Rollback operation identifier was reused with different writes')
                return {'skipped':True,'changes':0}
            for change in changes:
                table=change['table'];before=change.get('before');after=change.get('after')
                if table not in self.mapping or (before is None and after is None):raise ValueError('Unsupported rollback source')
                profile=self.mapping[table]
                for raw in [before,after]:
                    if raw is not None and set(json.loads(raw))!=set(profile['columns']):raise ValueError('Rollback row does not match the complete captured contract')
                current,predicate,key_values=self.lookup(c,table,before or after)
                if before is None:
                    if current is not None:raise ValueError('Recovery target already contains the new record')
                else:
                    if current is None:raise ValueError('Recovery source record is missing')
                    # PostgreSQL normalizes timestamps, UUIDs and numeric
                    # columns when it stores them. Compare the complete typed
                    # before-image, while null masks still distinguish SQL
                    # NULL from JSON null. Raw string equality would reject a
                    # native timestamp ending .120000 after it becomes .12.
                    c.execute(sql.SQL('SELECT to_jsonb(r)=%s::jsonb FROM jsonb_populate_record(NULL::public.{},%s::jsonb) r').format(sql.Identifier(table)),(current[0],before))
                    if not c.fetchone()[0] or sorted(change.get('before_sql_null_fields',[]))!=sorted(current[1]):raise ValueError('Recovery source has conflicting newer data')
                if before is not None and after is not None:
                    if any(json.loads(before)[field]!=json.loads(after)[field] for field in profile['primary_key']):
                        raise ValueError('Registry record identities must remain immutable during recovery')
                if before is not None and after is None:
                    c.execute(sql.SQL('DELETE FROM public.{} WHERE {}').format(sql.Identifier(table),predicate),key_values)
                if after is not None:
                    fields=list(profile['columns']);expressions=[];params=[]
                    nulls=change.get('after_sql_null_fields',[])
                    if set(nulls)-{field for field,meta in profile['columns'].items() if meta['type'] in {'json','jsonb'}}:raise ValueError('Invalid SQL-null column set')
                    for field in fields:
                        typ=profile['columns'][field]['type']
                        if typ in {'json','jsonb'}:
                            expressions.append(sql.SQL("CASE WHEN %s::jsonb -> {} = 'null'::jsonb AND NOT {}=ANY(%s::text[]) THEN 'null'::{} ELSE r.{} END").format(sql.Literal(field),sql.Literal(field),sql.SQL(typ),sql.Identifier(field)))
                            params.extend([after,nulls])
                        else:expressions.append(sql.SQL('r.{}').format(sql.Identifier(field)))
                    params.append(after)
                    if before is None:
                        query=sql.SQL('INSERT INTO public.{} ({}) OVERRIDING SYSTEM VALUE SELECT {} FROM jsonb_populate_record(NULL::public.{},%s::jsonb) r').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,fields)),sql.SQL(',').join(expressions),sql.Identifier(table))
                    else:
                        query=sql.SQL('UPDATE public.{} SET ({})=(SELECT {} FROM jsonb_populate_record(NULL::public.{},%s::jsonb) r) WHERE {}').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,fields)),sql.SQL(',').join(expressions),sql.Identifier(table),predicate)
                        params.extend(key_values)
                    c.execute(query,params)
            c.execute('INSERT INTO kdbt_native_rollback.receipts VALUES(%s,%s)',(operation_id,digest))
        return {'skipped':False,'changes':len(changes)}
