"""Data-only adapters for fenced SQL, SQLite, Redis and protected files."""
import base64,hashlib,json,os,secrets,sqlite3,stat,time
from pathlib import Path
from contextlib import contextmanager
import psycopg2
from psycopg2 import sql
from native_transaction_checkpoint import canonical,private,atomic
from native_auth_cache_transfer import snapshot

class SQLStore:
    def __init__(self,configuration,schema,*,production_scope=None):
        if schema not in {'certify','esignet','recovery_probe'}:raise ValueError('Explicit migration schema required')
        self.configuration,self.schema,self.scope=dict(configuration),schema,production_scope
        if not configuration['dbname'].startswith(('kdbt_original_','kdbt_transfer_')):
            from native_remaining_three_projection_scope import ProductionProjectionScope,fingerprint
            if not isinstance(production_scope,ProductionProjectionScope):
                raise ValueError('Exact production projection scope required')
            production_scope.authorize_store(configuration,schema)
    def connection(self):
        if self.scope:self.scope.require()
        return psycopg2.connect(**self.configuration,connect_timeout=5)
    def inventory(self,cursor):
        cursor.execute('''SELECT c.relname,a.attname,a.attnum,a.atttypid,a.attnotnull,a.attidentity,a.attgenerated,
            pg_get_expr(d.adbin,d.adrelid) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
            LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
            WHERE n.nspname=%s AND c.relkind='r' ORDER BY c.relname,a.attnum''',(self.schema,))
        values=cursor.fetchall()
        if not values or len({v[0] for v in values})>64 or any(v[6] for v in values):
            raise ValueError('Bounded ordinary table schema required')
        return values
    def identity(self):
        with self.connection() as c,c.cursor() as cursor:
            cursor.execute('SELECT oid FROM pg_database WHERE datname=current_database()');oid=cursor.fetchone()[0]
            cursor.execute('SELECT system_identifier::text FROM pg_control_system()');cluster=cursor.fetchone()[0]
            return {'kind':'postgresql','host':self.configuration['host'],'database':self.configuration['dbname'],
                'schema':self.schema,'database_oid':oid,'cluster':cluster,'schema_sha256':hashlib.sha256(canonical(self.inventory(cursor))).hexdigest()}
    def capture(self):
        with self.connection() as c,c.cursor() as cursor:
            c.set_session(isolation_level='REPEATABLE READ',readonly=True)
            cursor.execute("SET LOCAL statement_timeout='30s'")
            inventory=self.inventory(cursor);tables=sorted({v[0] for v in inventory});rows={};total=0
            for table in tables:
                cursor.execute(sql.SQL('SELECT row_to_json(t)::text FROM {} t ORDER BY row_to_json(t)::text').format(sql.Identifier(self.schema,table)))
                values=[]
                while True:
                    batch=cursor.fetchmany(500)
                    if not batch:break
                    for value, in batch:
                        total+=len(value.encode());values.append(value)
                        if total>128*1024*1024 or len(values)>100000:raise ValueError('SQL checkpoint capacity exceeded')
                rows[table]=values
            cursor.execute('SELECT sequencename FROM pg_sequences WHERE schemaname=%s ORDER BY sequencename',(self.schema,))
            sequences={}
            for name, in cursor.fetchall():
                cursor.execute(sql.SQL('SELECT last_value,is_called FROM {}').format(sql.Identifier(self.schema,name)))
                sequences[name]=list(cursor.fetchone())
            return canonical({'inventory':inventory,'rows':rows,'sequences':sequences})
    def validate(self,value):
        state=json.loads(value)
        if set(state)!={'inventory','rows','sequences'} or set(state['rows'])!={v[0] for v in state['inventory']}:raise ValueError('SQL inventory differs')
        if len(state['rows'])>64 or any(len(v)>100000 or not all(isinstance(r,str) for r in v) for v in state['rows'].values()):raise ValueError('SQL row bound exceeded')
        for table,rows in state['rows'].items():
            columns={v[1] for v in state['inventory'] if v[0]==table}
            if any(set(json.loads(r))!=columns for r in rows):raise ValueError('SQL column snapshot differs')
        for pair in state['sequences'].values():
            if len(pair)!=2 or type(pair[0]) is not int or type(pair[1]) is not bool:raise ValueError('Invalid sequence state')
        with self.connection() as c,c.cursor() as cursor:
            self.dependency_order(cursor,state)
            cursor.execute("SELECT 1 FROM pg_constraint fk JOIN pg_class p ON p.oid=fk.confrelid JOIN pg_namespace pn ON pn.oid=p.relnamespace JOIN pg_class child ON child.oid=fk.conrelid JOIN pg_namespace cn ON cn.oid=child.relnamespace WHERE fk.contype='f' AND pn.nspname=%s AND cn.nspname<>%s LIMIT 1",(self.schema,self.schema))
            if cursor.fetchone():raise ValueError('Incoming cross-schema constraint requires its own adapter')
    def summary(self,value):
        state=json.loads(value);return {'tables':len(state['rows']),'rows':sum(map(len,state['rows'].values())),'sequences':len(state['sequences'])}
    def dependency_order(self,cursor,state):
        tables=set(state['rows']);dependencies={t:set() for t in tables}
        cursor.execute('''SELECT child.relname,pn.nspname,parent.relname FROM pg_constraint fk
            JOIN pg_class child ON child.oid=fk.conrelid JOIN pg_namespace cn ON cn.oid=child.relnamespace
            JOIN pg_class parent ON parent.oid=fk.confrelid JOIN pg_namespace pn ON pn.oid=parent.relnamespace
            WHERE fk.contype='f' AND cn.nspname=%s''',(self.schema,))
        for child,parent_schema,parent in cursor.fetchall():
            if child in tables:
                if parent_schema!=self.schema or parent not in tables or child==parent:raise ValueError('Cross-boundary or recursive recovery constraint requires its own adapter')
                dependencies[child].add(parent)
        order=[]
        while len(order)<len(tables):
            ready=sorted(t for t in tables-set(order) if dependencies[t]<=set(order))
            if not ready:raise ValueError('Cyclic recovery constraint requires its own adapter')
            order+=ready
        return order
    def restore(self,value):
        self.validate(value);state=json.loads(value)
        with self.connection() as c,c.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='5s'");cursor.execute("SET LOCAL statement_timeout='60s'")
            if canonical(self.inventory(cursor))!=canonical(state['inventory']):raise ValueError('SQL schema changed')
            order=self.dependency_order(cursor,state)
            # Preserve table OIDs and live prepared statements. No trigger or
            # foreign-key checks are disabled, and no CASCADE crosses the scope.
            cursor.execute(sql.SQL('TRUNCATE {} CONTINUE IDENTITY').format(sql.SQL(',').join(sql.Identifier(self.schema,t) for t in sorted(state['rows']))))
            for table in order:
                if state['rows'][table]:
                    payload='['+','.join(state['rows'][table])+']'
                    cursor.execute(sql.SQL('INSERT INTO {} OVERRIDING SYSTEM VALUE SELECT * FROM json_populate_recordset(NULL::{},%s::json)').format(
                        sql.Identifier(self.schema,table),sql.Identifier(self.schema,table)),(payload,))
            for name,(last,called) in state['sequences'].items():
                cursor.execute('SELECT setval(%s::regclass,%s,%s)',(sql.Identifier(self.schema,name).as_string(c),last,called))
        self.verify(value)
    def verify(self,value):
        if self.capture()!=value:raise ValueError('SQL recovery did not reproduce the complete checkpoint')

class SQLiteStore:
    def __init__(self,path):self.path=Path(path).resolve(strict=True)
    def identity(self):
        private(self.path)
        with sqlite3.connect(self.path) as c:
            schema=c.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        return {'kind':'sqlite','path':str(self.path),'inode':self.path.stat().st_ino,'schema_sha256':hashlib.sha256(canonical(schema)).hexdigest()}
    @contextmanager
    def opened(self,value=None):
        path=self.path.parent/('checkpoint-sqlite-'+secrets.token_hex(16)+'.sqlite')
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        try:
            if value is not None:
                with os.fdopen(fd,'wb',closefd=False) as stream:stream.write(value);stream.flush();os.fsync(fd)
        finally:os.close(fd)
        connection=None
        try:
            connection=sqlite3.connect('file:'+str(path)+'?mode=ro&immutable=1',uri=True) if value is not None else sqlite3.connect(path)
            yield connection,path
        finally:
            if connection:connection.close()
            for suffix in ['', '-wal','-shm']:Path(str(path)+suffix).unlink(missing_ok=True)
    def capture(self):
        with sqlite3.connect(self.path) as source,self.opened() as (destination,path):
            source.backup(destination);destination.execute('PRAGMA journal_mode=DELETE');destination.commit()
            return path.read_bytes()
    def validate(self,value):
        with self.opened(value) as (c,_):
            if c.execute('PRAGMA quick_check').fetchone()!=('ok',) or c.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Invalid SQLite checkpoint')
    def summary(self,value):
        with self.opened(value) as (c,_):
            tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            return {'tables':len(tables),'rows':sum(c.execute('SELECT count(*) FROM "'+t.replace('"','""')+'"').fetchone()[0] for t in tables)}
    def logical(self,value):
        with self.opened(value) as (c,_):
            return '\n'.join(c.iterdump()).encode()
    def restore(self,value):
        self.validate(value)
        with self.opened(value) as (source,_),sqlite3.connect(self.path) as destination:
            source.backup(destination)
        self.verify(value)
    def verify(self,value):
        if self.logical(self.capture())!=self.logical(value):raise ValueError('SQLite recovery differs')

class RedisStore:
    def __init__(self,client):self.client=client
    def identity(self):
        info=self.client.info('server');configuration=self.client.connection_pool.connection_kwargs
        return {'kind':'redis','run_id':info['run_id'],'database':configuration.get('db',0),'host':configuration.get('host'),'port':configuration.get('port')}
    def capture(self):
        return canonical([[base64.b64encode(k).decode(),base64.b64encode(v).decode(),deadline] for k,(v,deadline) in sorted(snapshot(self.client,excluded=frozenset()).items())])
    def validate(self,value):
        records=json.loads(value);seen=set()
        if len(records)>100000:raise ValueError('Redis record bound exceeded')
        for key,data,expiry in records:
            raw=base64.b64decode(key,validate=True);base64.b64decode(data,validate=True)
            if raw in seen or type(expiry) is not int or expiry<0:raise ValueError('Invalid Redis checkpoint')
            seen.add(raw)
    def summary(self,value):return {'keys':len(json.loads(value))}
    def records(self,value):return {base64.b64decode(k):(base64.b64decode(v),d) for k,v,d in json.loads(value)}
    def restore(self,value):
        self.validate(value);records=self.records(value);clock=self.client.time();now=clock[0]*1000+clock[1]//1000
        for key,(data,deadline) in records.items():
            if deadline and deadline<=now:self.client.delete(key)
            else:self.client.restore(key,deadline,data,replace=True,absttl=bool(deadline))
        for key in self.client.scan_iter(count=200):
            if key not in records:self.client.delete(key)
        self.verify(value)
    def verify(self,value):
        clock=self.client.time();now=clock[0]*1000+clock[1]//1000
        before={k:v for k,v in self.records(value).items() if not v[1] or v[1]>now+20}
        after={k:v for k,v in self.records(self.capture()).items() if not v[1] or v[1]>now+20}
        if set(before)!=set(after) or any(before[k][0]!=after[k][0] or abs(before[k][1]-after[k][1])>2 for k in before):raise ValueError('Redis contents or absolute expiry differ')

class FileStore:
    def __init__(self,paths):
        if any(Path(v).is_symlink() for v in paths.values()):raise ValueError('Runtime file links are not allowed')
        self.paths={k:Path(v).resolve(strict=True) for k,v in paths.items()}
        if not self.paths or len(self.paths)>32:raise ValueError('Bounded explicit file inventory required')
        self.ownership={}
        for key,path in self.paths.items():
            info=path.stat()
            if info.st_uid not in {0,1001} or info.st_mode&0o077 or not stat.S_ISREG(info.st_mode):raise ValueError('Private runtime-owner file required')
            self.ownership[key]={'uid':info.st_uid,'gid':info.st_gid,'mode':info.st_mode&0o777}
    def read(self,key):
        fd=os.open(self.paths[key],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info=os.fstat(fd);expected=self.ownership[key]
            if (not stat.S_ISREG(info.st_mode) or info.st_size>32*1024*1024
                    or (info.st_uid,info.st_gid,info.st_mode&0o777)!=(expected['uid'],expected['gid'],expected['mode'])):raise ValueError('Runtime file identity or permissions differ')
            with os.fdopen(fd,'rb',closefd=False) as stream:return stream.read(32*1024*1024+1)
        finally:os.close(fd)
    def identity(self):
        for key in self.paths:self.read(key)
        return {'kind':'protected-files','paths':{k:{'path':str(v),**self.ownership[k]} for k,v in self.paths.items()}}
    def capture(self):return canonical({k:base64.b64encode(self.read(k)).decode() for k in self.paths})
    def validate(self,value):
        state=json.loads(value)
        if set(state)!=set(self.paths):raise ValueError('Protected file inventory differs')
        for data in state.values():
            if len(base64.b64decode(data,validate=True))>32*1024*1024:raise ValueError('Protected file size bound exceeded')
    def summary(self,value):return {'files':len(json.loads(value))}
    def restore(self,value):
        self.validate(value)
        for key,data in json.loads(value).items():
            atomic(self.paths[key],base64.b64decode(data));metadata=self.ownership[key]
            os.chown(self.paths[key],metadata['uid'],metadata['gid']);os.chmod(self.paths[key],metadata['mode'])
    def verify(self,value):
        if self.capture()!=value:raise ValueError('Protected file contents differ')
