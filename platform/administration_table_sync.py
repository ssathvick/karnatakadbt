"""Conflict-checked physical projections for independently implemented APIs.

Reuses the durable transaction journal. PostgreSQL decodes row images itself so
bytea, JSON nulls, decimals, timestamps and composite keys are not coerced by
Python. Never attach this projector to a writable production destination.
"""
from psycopg2 import sql
class AdministrationDestination:
    """Validate projected FK state before the journal commits and acknowledges."""
    def __init__(self,connection,projector):self.connection=connection;self.projector=projector
    def __getattr__(self,name):return getattr(self.connection,name)
    def commit(self):
        with self.connection.cursor() as c:self.projector.validate_constraints(c)
        self.connection.commit()

class AdministrationTableProjector:
    def __init__(self,contract):self.contract=contract
    def predicate(self,table):return sql.SQL(' AND ').join(sql.SQL('t.{} IS NOT DISTINCT FROM r.{}').format(sql.Identifier(key),sql.Identifier(key)) for key in self.contract[table]['keys'])
    def lookup(self,c,table,raw):
        c.execute(sql.SQL('SELECT to_jsonb(t)=%s::jsonb FROM public.{} t CROSS JOIN jsonb_populate_record(NULL::public.{},%s::jsonb) r WHERE {}').format(sql.Identifier(table),sql.Identifier(table),self.predicate(table)),(raw,raw));return c.fetchone()
    def remove(self,c,table,raw,*,check=True):
        match=self.lookup(c,table,raw)
        if check and (match is None or not match[0]):raise ValueError('ADMINISTRATION_NATIVE_WRITE_CONFLICT')
        c.execute(sql.SQL('DELETE FROM public.{} t USING jsonb_populate_record(NULL::public.{},%s::jsonb) r WHERE {}').format(sql.Identifier(table),sql.Identifier(table),self.predicate(table)),(raw,))
    def put(self,c,table,raw,nulls):
        meta=self.contract[table];columns=[column[0] for column in meta['columns']];jsons={column[0]:column[1] for column in meta['columns'] if column[1] in {'json','jsonb'}}
        expressions=[]
        for name in columns:
            if name in jsons:
                expressions.append(sql.SQL('CASE WHEN {}=ANY(v.nulls) THEN NULL ELSE (v.data -> {})::{} END').format(sql.Literal(name),sql.Literal(name),sql.SQL(jsons[name])))
            else:expressions.append(sql.SQL('r.{}').format(sql.Identifier(name)))
        c.execute(sql.SQL('WITH v AS (SELECT %s::jsonb AS data,%s::text[] AS nulls) INSERT INTO public.{} ({}) SELECT {} FROM v CROSS JOIN LATERAL jsonb_populate_record(NULL::public.{},v.data) r').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,columns)),sql.SQL(',').join(expressions),sql.Identifier(table)),(raw,nulls))
    def event(self,c,table,operation,before,after,nulls):
        if table not in self.contract:raise ValueError('Unknown administration source table')
        # Source FK cascades already have their own journal row images. Avoid
        # executing them a second time in a different AFTER-trigger order.
        # AdministrationDestination validates the final FKs before any commit.
        c.execute('SET LOCAL session_replication_role=replica')
        if operation=='TRUNCATE':
            c.execute(sql.SQL('TRUNCATE public.{} CASCADE').format(sql.Identifier(table)));return
        if before is not None:self.remove(c,table,before)
        if after is not None:
            if self.lookup(c,table,after) is not None:raise ValueError('ADMINISTRATION_NATIVE_INSERT_CONFLICT')
            self.put(c,table,after,nulls)
    def insertion_order(self,c):
        c.execute("SELECT child.relname,parent.relname FROM pg_constraint k JOIN pg_class child ON child.oid=k.conrelid JOIN pg_class parent ON parent.oid=k.confrelid JOIN pg_namespace n ON n.oid=child.relnamespace WHERE k.contype='f' AND n.nspname='public'")
        dependencies={name:set() for name in self.contract}
        for child,parent in c.fetchall():
            if child in dependencies and parent in dependencies and child!=parent:dependencies[child].add(parent)
        order=[]
        while dependencies:
            ready=sorted(name for name,parents in dependencies.items() if parents.issubset(order))
            if not ready:raise ValueError('Explicit migration order required for cyclic foreign keys')
            for name in ready:order.append(name);dependencies.pop(name)
        return order
    def seed(self,c,mirror_schema,source_id):
        order=self.insertion_order(c)
        c.execute('SET LOCAL session_replication_role=replica')
        c.execute(sql.SQL('TRUNCATE {} CASCADE').format(sql.SQL(',').join(sql.SQL('public.{}').format(sql.Identifier(name)) for name in order)))
        counts={}
        for name in order:
            c.execute(sql.SQL('SELECT data::text,sql_null_fields FROM {}.rows WHERE source_id=%s AND table_name=%s').format(sql.Identifier(mirror_schema)),(source_id,name));rows=c.fetchall()
            for raw,nulls in rows:self.put(c,name,raw,nulls)
            counts[name]=len(rows)
        self.validate_constraints(c);return counts
    def validate_constraints(self,c):
        c.execute("""SELECT child.relname,pn.nspname,parent.relname,k.confmatchtype,
        ARRAY(SELECT a.attname FROM unnest(k.conkey) WITH ORDINALITY x(attnum,n) JOIN pg_attribute a ON a.attrelid=child.oid AND a.attnum=x.attnum ORDER BY x.n),
        ARRAY(SELECT a.attname FROM unnest(k.confkey) WITH ORDINALITY x(attnum,n) JOIN pg_attribute a ON a.attrelid=parent.oid AND a.attnum=x.attnum ORDER BY x.n)
        FROM pg_constraint k JOIN pg_class child ON child.oid=k.conrelid JOIN pg_namespace cn ON cn.oid=child.relnamespace JOIN pg_class parent ON parent.oid=k.confrelid JOIN pg_namespace pn ON pn.oid=parent.relnamespace WHERE k.contype='f' AND cn.nspname='public'""")
        for child,namespace,parent,match,children,parents in c.fetchall():
            nonnull=sql.SQL(' AND ').join(sql.SQL('t.{} IS NOT NULL').format(sql.Identifier(key)) for key in children)
            predicate=sql.SQL(' AND ').join(sql.SQL('p.{}=t.{}').format(sql.Identifier(p),sql.Identifier(k)) for k,p in zip(children,parents))
            c.execute(sql.SQL('SELECT EXISTS(SELECT 1 FROM public.{} t WHERE {} AND NOT EXISTS(SELECT 1 FROM {}.{} p WHERE {}))').format(sql.Identifier(child),nonnull,sql.Identifier(namespace),sql.Identifier(parent),predicate))
            if c.fetchone()[0]:raise ValueError('ADMINISTRATION_FOREIGN_KEY_RECONCILIATION_REQUIRED')
            if match=='f':
                anynull=sql.SQL(' OR ').join(sql.SQL('t.{} IS NULL').format(sql.Identifier(key)) for key in children)
                anynonnull=sql.SQL(' OR ').join(sql.SQL('t.{} IS NOT NULL').format(sql.Identifier(key)) for key in children)
                c.execute(sql.SQL('SELECT EXISTS(SELECT 1 FROM public.{} t WHERE ({}) AND ({}))').format(sql.Identifier(child),anynull,anynonnull))
                if c.fetchone()[0]:raise ValueError('ADMINISTRATION_FOREIGN_KEY_RECONCILIATION_REQUIRED')
    def sequences(self,source,destination):
        # Source sequences are not transactional; copy their latest state after
        # each batch, never move the destination backwards across a retry.
        with source.cursor() as s,destination.cursor() as d:
            s.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='public' ORDER BY 1")
            for (name,) in s.fetchall():
                s.execute(sql.SQL('SELECT last_value,is_called FROM public.{}').format(sql.Identifier(name)));value,called=s.fetchone()
                d.execute(sql.SQL('SELECT last_value,is_called FROM public.{}').format(sql.Identifier(name)));existing,existing_called=d.fetchone()
                d.execute('SELECT setval(%s::regclass,%s,%s)',('public.'+name,max(value,existing),called or existing_called))
