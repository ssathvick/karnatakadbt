"""Transactional projections for registry workflow rows and intake snapshots."""
import hashlib,json,uuid
from pathlib import Path
from psycopg2 import sql
from registry_json_sync import NativeJsonProjector
from registry_row_store import RegistryRowStore


def structured_specs():
    folder=Path(__file__).parent;result={}
    for kind,profile in json.loads((folder/'registry_row_contract.json').read_text()).items():
        result[profile['source_table']]={'target':'console_registry_rows','kind':kind,'kind_column':'kind','primary_key':profile['primary_key'],'intake':False}
    for register,profile in json.loads((folder/'registry_intake_record_contract.json').read_text()).items():
        if profile is None:continue
        if profile['source_table'] in result:raise ValueError('Ambiguous structured source table')
        result[profile['source_table']]={'target':'console_intake_snapshots','kind':register,'kind_column':'register_id','primary_key':profile['primary_key'],'intake':True}
    return result


class NativeStructuredProjector(NativeJsonProjector):
    def __init__(self,native_schema='public'):
        super().__init__(native_schema,structured_specs())

    def key(self,table,raw):
        value=json.loads(raw);fields=[value[k] for k in self.mapping[table]['primary_key']]
        if any(v is None or isinstance(v,(dict,list,bool,float)) for v in fields):raise ValueError('Stable structured identity required')
        return hashlib.sha256(json.dumps(fields,sort_keys=True,default=str).encode()).hexdigest()

    def where(self,table):
        return sql.SQL('{}=%s AND key=%s').format(sql.Identifier(self.mapping[table]['kind_column']))

    def put(self,c,table,raw,nulls=None,*,seeding=False):
        meta=self.mapping[table];value=json.loads(raw);key=self.key(table,raw);nulls=nulls or []
        if seeding:
            c.execute(sql.SQL('SELECT data::jsonb=%s::jsonb FROM {}.{} WHERE {}').format(sql.Identifier(self.schema),sql.Identifier(meta['target']),self.where(table)),(raw,meta['kind'],key))
            existing=c.fetchone()
            if existing is not None and not existing[0]:raise ValueError('Existing structured native row differs from source mirror')
        else:self.ensure_unchanged(c,table,key)
        attributes={meta['kind_column']:meta['kind'],'key':key}
        if meta['intake']:
            attributes.update(submission_id=str(uuid.UUID(value['submission_id'])),record_id=value.get('internal_record_id'),
                link_id=value.get('link_internal_record_id'),section_id=value.get('section_id'),source_json=raw)
        else:attributes.update(RegistryRowStore.row_attributes(None,meta['kind'],value))
        columns=[sql.Identifier(name) for name in attributes];parameters=list(attributes.values());placeholders=[sql.Placeholder() for _ in attributes]
        columns.append(sql.Identifier('data'));parameters.append(raw);placeholders.append(sql.SQL('%s::jsonb'))
        if meta['intake']:
            columns.append(sql.Identifier('json_null_fields'));parameters.append(json.dumps(nulls));placeholders.append(sql.SQL('%s::jsonb'))
        updates=[sql.SQL('{}=excluded.{}').format(name,name) for name in columns if name.as_string(c) not in {sql.Identifier(meta['kind_column']).as_string(c),sql.Identifier('key').as_string(c)}]
        c.execute(sql.SQL('INSERT INTO {}.{} ({}) VALUES ({}) ON CONFLICT({},key) DO UPDATE SET {}').format(
            sql.Identifier(self.schema),sql.Identifier(meta['target']),sql.SQL(',').join(columns),sql.SQL(',').join(placeholders),sql.Identifier(meta['kind_column']),sql.SQL(',').join(updates)),parameters)
        c.execute(sql.SQL('INSERT INTO {}.native_json_sync_state VALUES(%s,%s,%s) ON CONFLICT(source_table,native_key) DO UPDATE SET digest=excluded.digest').format(sql.Identifier(self.schema)),(table,key,self.fingerprint(c,table,key)))

    def seed(self,c,mirror_schema,source_id):
        self.initialize(c);counts={}
        for table,meta in self.mapping.items():
            c.execute(sql.SQL('SELECT data::text,sql_null_fields FROM {}.rows WHERE source_id=%s AND table_name=%s').format(sql.Identifier(mirror_schema)),(source_id,table));values=c.fetchall()
            for raw,nulls in values:self.put(c,table,raw,nulls,seeding=True)
            c.execute(sql.SQL('SELECT count(*) FROM {}.{} WHERE {}=%s').format(sql.Identifier(self.schema),sql.Identifier(meta['target']),sql.Identifier(meta['kind_column'])),(meta['kind'],))
            if c.fetchone()[0]!=len(values):raise ValueError('Native structured rows absent from source mirror')
            counts[table]=len(values)
        return counts

    def event(self,c,table,operation,before,after,nulls):
        if table not in self.mapping:return
        meta=self.mapping[table]
        if operation=='TRUNCATE':
            c.execute(sql.SQL('SELECT data::text FROM {}.{} WHERE {}=%s').format(sql.Identifier(self.schema),sql.Identifier(meta['target']),sql.Identifier(meta['kind_column'])),(meta['kind'],))
            for (raw,) in c.fetchall():self.remove(c,table,raw)
            return
        if before is not None and (after is None or self.key(table,before)!=self.key(table,after)):self.remove(c,table,before)
        if after is not None:self.put(c,table,after,nulls)
