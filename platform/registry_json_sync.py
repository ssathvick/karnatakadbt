"""Conflict-checked projection of configuration and message/score queue JSON.

This adapter intentionally does not cover identity sessions, document objects,
registry operational summaries, or admission queues with separate policy fields.
"""
import json
from pathlib import Path
from psycopg2 import sql

SPECS={}
def spec(source,target,kind,key,position=True,key_column='id'):
    SPECS[source]={'target':target,'kind':kind,'key':key,'position':position,'key_column':key_column}
for source,kind,key in [('g2p_register_definitions','register','register_id'),('g2p_intake_form_definitions','form','form_id'),('data_models','model','data_model_id'),('g2p_input_mechanisms','input','mechanism_id')]:spec(source,'console_definition_catalog',kind,key)
for source,kind,key in [('g2p_registry_awe_policy_configurations','awe','awe_policy_config_id'),('g2p_registry_vc_configurations','vc','vc_config_id'),('g2p_registry_import_file_configurations','import','import_file_configuration_id')]:spec(source,'console_workflow_input_configs',kind,key)
for source,kind,key in [('incoming_model_key_paths','key','key_path_id'),('incoming_model_semantic_patterns','semantic','semantic_pattern_id'),('incoming_model_register_semantic_patterns','register','register_semantic_pattern_id')]:spec(source,'console_ingestion_patterns',kind,key)
for source,kind,key in [('g2p_register_sections','section','section_id'),('g2p_register_ui_tabs','tab','tab_id'),('g2p_register_ui_tab_sections','link','tab_section_id'),('g2p_intake_form_ui_tabs','intake-tab','tab_id'),('g2p_intake_form_ui_tab_sections','intake-link','tab_section_id')]:spec(source,'console_register_layouts',kind,key)
for source,kind in [('incoming_templates','incoming'),('outgoing_templates','outgoing')]:spec(source,'console_message_templates',kind,'template_id')
for source,kind,key in [('g2p_register_score_definitions','definition','score_definition_id'),('g2p_register_score_contributing_attributes','attribute','contributing_attribute_id'),('g2p_score_compute_queue','queue','queue_id')]:spec(source,'console_score_configuration',kind,key)
for kind,profile in json.loads(Path(__file__).with_name('registry_message_data_contract.json').read_text()).items():spec(profile['source_table'],'console_message_data',kind,profile['primary_key'],False,'key')

class NativeJsonProjector:
    def __init__(self,native_schema='public',specs=None):self.schema=native_schema;self.mapping=SPECS if specs is None else specs
    def initialize(self,c):
        c.execute(sql.SQL('CREATE TABLE IF NOT EXISTS {}.native_json_sync_state(source_table text NOT NULL,native_key text NOT NULL,digest text NOT NULL,PRIMARY KEY(source_table,native_key))').format(sql.Identifier(self.schema)))
    def key(self,table,raw):
        value=json.loads(raw)[self.mapping[table]['key']]
        if value is None or isinstance(value,(dict,list,bool,float)):raise ValueError('Stable JSON projection identity required')
        return str(value)
    def where(self,table):
        return sql.SQL('kind=%s AND {}=%s').format(sql.Identifier(self.mapping[table]['key_column']))
    def fingerprint(self,c,table,key):
        meta=self.mapping[table]
        c.execute(sql.SQL("SELECT md5((to_jsonb(t)-'position')::text) FROM {}.{} t WHERE {}").format(sql.Identifier(self.schema),sql.Identifier(meta['target']),self.where(table)),(meta['kind'],key))
        row=c.fetchone();return row[0] if row else None
    def ensure_unchanged(self,c,table,key):
        c.execute(sql.SQL('SELECT digest FROM {}.native_json_sync_state WHERE source_table=%s AND native_key=%s FOR UPDATE').format(sql.Identifier(self.schema)),(table,key))
        expected=c.fetchone();actual=self.fingerprint(c,table,key)
        if (expected is None and actual is not None) or (expected is not None and expected[0]!=actual):raise ValueError('NATIVE_JSON_SYNC_CONFLICT')
    def put(self,c,table,raw,*,seeding=False):
        meta=self.mapping[table];key=self.key(table,raw)
        if seeding:
            c.execute(sql.SQL('SELECT data::jsonb=%s::jsonb FROM {}.{} WHERE {}').format(sql.Identifier(self.schema),sql.Identifier(meta['target']),self.where(table)),(raw,meta['kind'],key))
            existing=c.fetchone()
            if existing is not None and not existing[0]:raise ValueError('Existing native JSON row differs from source mirror')
        else:self.ensure_unchanged(c,table,key)
        columns=[sql.Identifier('kind'),sql.Identifier(meta['key_column']),sql.Identifier('data')]
        values=sql.SQL('%s,%s,%s::jsonb')
        if meta['position']:
            columns.append(sql.Identifier('position'))
            values+=sql.SQL(',coalesce((SELECT max(position) FROM {}.{}),0)+1').format(sql.Identifier(self.schema),sql.Identifier(meta['target']))
        c.execute(sql.SQL('INSERT INTO {}.{} ({}) VALUES({}) ON CONFLICT(kind,{}) DO UPDATE SET data=excluded.data').format(sql.Identifier(self.schema),sql.Identifier(meta['target']),sql.SQL(',').join(columns),values,sql.Identifier(meta['key_column'])),(meta['kind'],key,raw))
        c.execute(sql.SQL('INSERT INTO {}.native_json_sync_state VALUES(%s,%s,%s) ON CONFLICT(source_table,native_key) DO UPDATE SET digest=excluded.digest').format(sql.Identifier(self.schema)),(table,key,self.fingerprint(c,table,key)))
    def remove(self,c,table,raw):
        meta=self.mapping[table];key=self.key(table,raw);self.ensure_unchanged(c,table,key)
        c.execute(sql.SQL('DELETE FROM {}.{} WHERE {}').format(sql.Identifier(self.schema),sql.Identifier(meta['target']),self.where(table)),(meta['kind'],key))
        c.execute(sql.SQL('DELETE FROM {}.native_json_sync_state WHERE source_table=%s AND native_key=%s').format(sql.Identifier(self.schema)),(table,key))
    def seed(self,c,mirror_schema,source_id):
        self.initialize(c);counts={}
        for table,meta in self.mapping.items():
            c.execute(sql.SQL('SELECT data::text FROM {}.rows WHERE source_id=%s AND table_name=%s').format(sql.Identifier(mirror_schema)),(source_id,table));values=c.fetchall()
            for (raw,) in values:self.put(c,table,raw,seeding=True)
            c.execute(sql.SQL('SELECT count(*) FROM {}.{} WHERE kind=%s').format(sql.Identifier(self.schema),sql.Identifier(meta['target'])),(meta['kind'],))
            if c.fetchone()[0]!=len(values):raise ValueError('Native JSON projection contains rows absent from source mirror')
            counts[table]=len(values)
        return counts
    def event(self,c,table,operation,before,after,nulls):
        if table not in self.mapping:return
        meta=self.mapping[table]
        if operation=='TRUNCATE':
            c.execute(sql.SQL('SELECT data::text FROM {}.{} WHERE kind=%s').format(sql.Identifier(self.schema),sql.Identifier(meta['target'])),(meta['kind'],))
            for (raw,) in c.fetchall():self.remove(c,table,raw)
            return
        if before is not None and (after is None or self.key(table,before)!=self.key(table,after)):self.remove(c,table,before)
        if after is not None:self.put(c,table,after)
