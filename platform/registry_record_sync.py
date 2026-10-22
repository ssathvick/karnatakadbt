"""Source-to-native record projection with transaction-level conflict checks.

Only current/history records are covered here. Configuration, sessions, queues
and console metadata require their own adapters before a registry cutover.
"""
import datetime,hashlib,json
from pathlib import Path
from psycopg2 import sql
from registry_record_store import record_timestamp

class NativeRecordProjector:
    def __init__(self,native_schema='public',contracts=None):
        self.schema=native_schema
        contracts=contracts or json.loads(Path(__file__).with_name('registry_record_contract.json').read_text())
        self.mapping={}
        for interface in contracts.values():
            for kind in ['current','history']:
                profile=interface.get(kind)
                if not profile:continue
                table=profile['source_table']
                if table in self.mapping:raise ValueError('Ambiguous record source mapping')
                self.mapping[table]=(kind,interface['register_id'],profile)

    def initialize(self,c):
        c.execute(sql.SQL('CREATE TABLE IF NOT EXISTS {}.native_record_sync_state(source_table text NOT NULL,native_key text NOT NULL,digest text NOT NULL,PRIMARY KEY(source_table,native_key))').format(sql.Identifier(self.schema)))

    def key(self,table,raw):
        value=json.loads(raw)
        fields=[value[name] for name in self.mapping[table][2]['primary_key']]
        if any(isinstance(item,(float,dict,list)) for item in fields):raise ValueError('Unsupported record primary key')
        return hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()

    def fingerprint(self,c,table,key):
        kind,register,_=self.mapping[table]
        c.execute(sql.SQL("SELECT md5(data::text || ':' || coalesce(json_null_fields::text,'null')) FROM {}.console_record_snapshots WHERE kind=%s AND register_id=%s AND key=%s").format(sql.Identifier(self.schema)),(kind,register,key))
        row=c.fetchone()
        return row[0] if row else None

    def ensure_unchanged(self,c,table,key):
        c.execute(sql.SQL('SELECT digest FROM {}.native_record_sync_state WHERE source_table=%s AND native_key=%s FOR UPDATE').format(sql.Identifier(self.schema)),(table,key))
        expected=c.fetchone();current=self.fingerprint(c,table,key)
        if (expected is None and current is not None) or (expected is not None and current!=expected[0]):
            raise ValueError('NATIVE_RECORD_SYNC_CONFLICT')

    def put(self,c,table,raw,nulls,*,seeding=False):
        kind,register,profile=self.mapping[table];value=json.loads(raw);key=self.key(table,raw)
        if seeding:
            c.execute(sql.SQL('SELECT data=%s::jsonb AND coalesce(json_null_fields,\'[]\'::jsonb)=%s::jsonb FROM {}.console_record_snapshots WHERE kind=%s AND register_id=%s AND key=%s').format(sql.Identifier(self.schema)),(raw,json.dumps(nulls),kind,register,key))
            existing=c.fetchone()
            if existing is not None and not existing[0]:raise ValueError('Existing native snapshot differs from source mirror')
        else:self.ensure_unchanged(c,table,key)
        stamp=lambda field:record_timestamp(value[field]) if value.get(field) else None
        arguments=(kind,register,key,value.get('internal_record_id'),value.get('link_internal_record_id'),value.get('subject_internal_record_id'),value.get('tab_id'),value.get('section_id'),stamp('created_at'),stamp('approved_at'),raw,raw,json.dumps(nulls))
        c.execute(sql.SQL('''INSERT INTO {}.console_record_snapshots(kind,register_id,key,record_id,link_id,subject_id,tab_id,section_id,created_at,approved_at,source_json,data,json_null_fields)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
        ON CONFLICT(kind,register_id,key) DO UPDATE SET record_id=excluded.record_id,link_id=excluded.link_id,subject_id=excluded.subject_id,tab_id=excluded.tab_id,section_id=excluded.section_id,created_at=excluded.created_at,approved_at=excluded.approved_at,source_json=excluded.source_json,data=excluded.data,json_null_fields=excluded.json_null_fields''').format(sql.Identifier(self.schema)),arguments)
        c.execute(sql.SQL('INSERT INTO {}.native_record_sync_state VALUES(%s,%s,%s) ON CONFLICT(source_table,native_key) DO UPDATE SET digest=excluded.digest').format(sql.Identifier(self.schema)),(table,key,self.fingerprint(c,table,key)))

    def remove(self,c,table,raw):
        kind,register,_=self.mapping[table];key=self.key(table,raw)
        self.ensure_unchanged(c,table,key)
        c.execute(sql.SQL('DELETE FROM {}.console_record_snapshots WHERE kind=%s AND register_id=%s AND key=%s').format(sql.Identifier(self.schema)),(kind,register,key))
        c.execute(sql.SQL('DELETE FROM {}.native_record_sync_state WHERE source_table=%s AND native_key=%s').format(sql.Identifier(self.schema)),(table,key))

    def seed(self,c,mirror_schema,source_id):
        self.initialize(c);count=0
        for table in self.mapping:
            c.execute(sql.SQL('SELECT data::text,sql_null_fields FROM {}.rows WHERE source_id=%s AND table_name=%s').format(sql.Identifier(mirror_schema)),(source_id,table))
            values=c.fetchall()
            for raw,nulls in values:self.put(c,table,raw,nulls,seeding=True);count+=1
            kind,register,_=self.mapping[table]
            c.execute(sql.SQL('SELECT count(*) FROM {}.console_record_snapshots WHERE kind=%s AND register_id=%s').format(sql.Identifier(self.schema)),(kind,register))
            if c.fetchone()[0]!=len(values):raise ValueError('Native snapshot contains records absent from the source mirror')
        return count

    def event(self,c,table,operation,before,after,nulls):
        if table not in self.mapping:return
        if operation=='TRUNCATE':
            kind,register,_=self.mapping[table]
            c.execute(sql.SQL('SELECT source_json FROM {}.console_record_snapshots WHERE kind=%s AND register_id=%s').format(sql.Identifier(self.schema)),(kind,register))
            for (raw,) in c.fetchall():self.remove(c,table,raw)
            return
        if before is not None and (after is None or self.key(table,before)!=self.key(table,after)):
            self.remove(c,table,before)
        if after is not None:self.put(c,table,after,nulls)
