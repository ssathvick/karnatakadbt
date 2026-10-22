"""Remaining registry source state, with explicit import and schema semantics."""
import json
from psycopg2 import sql
from registry_auxiliary_sync import NativeAuxiliaryProjector,digest_key


class NativeRemainingProjector(NativeAuxiliaryProjector):
    def __init__(self,native_schema='public'):
        super().__init__(native_schema)
        self.mapping={
            'g2p_register_schemas':('schema','register_id'),
            'import_file_process_queue':('import','import_file_id'),
            'import_file_process_log':('import-history','import_file_record_id'),
            'ng2p_geography_areas':('reference','area_id'),
            'g2p_registry_data_policies':('reference','policy_id')}

    def initialize(self,c):
        super().initialize(c)
        c.execute(sql.SQL('CREATE TABLE IF NOT EXISTS {}.native_registry_reference_data(kind text NOT NULL,id text NOT NULL,data jsonb NOT NULL,PRIMARY KEY(kind,id))').format(sql.Identifier(self.schema)))
        c.execute(sql.SQL('CREATE TABLE IF NOT EXISTS {}.native_registry_import_history(id text PRIMARY KEY,document_id text NOT NULL,record_number integer NOT NULL,import_file_id text NOT NULL,at timestamp NOT NULL,data jsonb NOT NULL)').format(sql.Identifier(self.schema)))
        c.execute(sql.SQL('CREATE INDEX IF NOT EXISTS native_registry_import_history_position ON {}.native_registry_import_history(document_id,record_number)').format(sql.Identifier(self.schema)))

    def source_key(self,table,raw):
        value=json.loads(raw)[self.mapping[table][1]]
        if value is None:raise ValueError('Missing remaining source identity')
        return digest_key([value])

    def outputs(self,c,table,raw):
        family,key=self.mapping[table];v=json.loads(raw)
        if family=='reference':return [('native_registry_reference_data',{'kind':table,'id':str(v[key])},{},raw)]
        if family=='import':
            if not v.get('queued_by'):raise ValueError('Import source requester must be preserved')
            # The source has no policy snapshot. [] records that absence and
            # confers no authority: the worker requires its own verified IAM
            # principal before every row admission.
            return [('console_registry_import_queue',{'id':v[key]},{'document_id':v['document_id'],'status':v['intake_form_ingestion_status'],'queued_at':v['queued_at'],'actor':v['queued_by'],'policy_context':[]},raw)]
        if family=='import-history':return [('native_registry_import_history',{'id':v[key]},{'document_id':v['document_id'],'record_number':v['record_number'],'import_file_id':v['import_file_id'],'at':v['ingestion_timestamp']},raw)]
        c.execute("SELECT (%s::jsonb-'register_id')::text",(raw,));return [('console_register_definition_state',{'id':v[key]},{},c.fetchone()[0])]

    def assert_output(self,c,output,allow_missing=False):
        target,keys,attrs,raw=output
        if target!='console_register_definition_state':return super().assert_output(c,output,allow_missing)
        c.execute(sql.SQL("SELECT CASE WHEN data::jsonb->'schema'='null'::jsonb THEN NULL ELSE data::jsonb->'schema'=%s::jsonb END FROM {}.{} WHERE id=%s").format(sql.Identifier(self.schema),sql.Identifier(target)),(raw,keys['id']));row=c.fetchone()
        if (row is None or row[0] is None) and allow_missing:return False
        if row is None or not row[0]:raise ValueError('NATIVE_SCHEMA_SYNC_CONFLICT')
        return True

    def put_output(self,c,output):
        target,keys,attrs,raw=output
        if target!='console_register_definition_state':return super().put_output(c,output)
        c.execute(sql.SQL("UPDATE {}.{} SET data=jsonb_set(data::jsonb,'{{schema}}',%s::jsonb) WHERE id=%s").format(sql.Identifier(self.schema),sql.Identifier(target)),(raw,keys['id']))
        if c.rowcount!=1:raise ValueError('Register definition fields and occupancy must already exist')

    def remove_output(self,c,output):
        target,keys,_,_=output
        if target!='console_register_definition_state':return super().remove_output(c,output)
        c.execute(sql.SQL("UPDATE {}.{} SET data=jsonb_set(data::jsonb,'{{schema}}','null'::jsonb) WHERE id=%s").format(sql.Identifier(self.schema),sql.Identifier(target)),(keys['id'],))

    def output_exists(self,c,output):
        target,keys,_,_=output
        if target!='console_register_definition_state':return super().output_exists(c,output)
        c.execute(sql.SQL("SELECT data::jsonb->'schema' IS NOT NULL AND data::jsonb->'schema'<>'null'::jsonb FROM {}.{} WHERE id=%s FOR UPDATE").format(sql.Identifier(self.schema),sql.Identifier(target)),(keys['id'],));row=c.fetchone()
        return bool(row and row[0])

    def namespace_outputs(self,table):
        family,_=self.mapping[table]
        if family=='reference':return [('native_registry_reference_data',{'kind':table})]
        return [({'schema':'console_register_definition_state','import':'console_registry_import_queue','import-history':'native_registry_import_history'}[family],{})]

    def seed(self,c,mirror_schema,source_id):
        # Definition state has rows for registers with no schema. Its count is
        # intentionally not a source schema-row count.
        schema_spec=self.mapping.pop('g2p_register_schemas')
        try:counts=super().seed(c,mirror_schema,source_id)
        finally:self.mapping['g2p_register_schemas']=schema_spec
        c.execute(sql.SQL('SELECT data::text FROM {}.rows WHERE source_id=%s AND table_name=%s').format(sql.Identifier(mirror_schema)),(source_id,'g2p_register_schemas'));rows=c.fetchall()
        for (raw,) in rows:
            for output in self.outputs(c,'g2p_register_schemas',raw):
                if not self.assert_output(c,output,True):self.put_output(c,output)
            c.execute(sql.SQL('INSERT INTO {}.native_auxiliary_sync_state VALUES(%s,%s,%s) ON CONFLICT(source_table,source_key) DO UPDATE SET raw=excluded.raw').format(sql.Identifier(self.schema)),('g2p_register_schemas',self.source_key('g2p_register_schemas',raw),raw))
        counts['g2p_register_schemas']=len(rows);return counts
