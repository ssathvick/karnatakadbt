"""Read a complete source-schema recovery snapshot from native registry state.

JSON payloads stay PostgreSQL text throughout, preserving numeric precision.
The frozen source baseline supplies SQL/JSON null distinctions that plain JSON
projections cannot express. New opaque/private state is not guessed: missing
required source fields block recovery rather than fabricate beneficiary data.
"""
import json
from cryptography.fernet import Fernet
from psycopg2 import sql
from registry_json_sync import SPECS
from registry_operational_sync import OPERATIONAL_SPECS
from registry_structured_sync import structured_specs
from registry_record_sync import NativeRecordProjector
from registry_auxiliary_sync import NativeAuxiliaryProjector
from registry_remaining_sync import NativeRemainingProjector

class NativeSnapshotIncomplete(ValueError):pass

class NativeRegistrySnapshot:
    def __init__(self,contract,*,identity_key=None):
        self.contract=contract;self.records=NativeRecordProjector().mapping;self.structured=structured_specs();self.auxiliary=NativeAuxiliaryProjector().mapping;self.remaining=NativeRemainingProjector().mapping
        self.identity_cipher=Fernet(identity_key.encode() if isinstance(identity_key,str) else identity_key) if identity_key else None
        covered=set(self.records)|set(SPECS)|set(OPERATIONAL_SPECS)|set(self.structured)|set(self.auxiliary)|set(self.remaining)|{'g2p_registrant_authentication_providers','g2p_registrant_authentications'}
        if set(contract)!=covered:raise NativeSnapshotIncomplete('Recovery snapshot source families do not match the complete captured contract')
    def identity(self,table,raw):
        value=json.loads(raw)
        try:result=tuple(str(value[field]) for field in self.contract[table]['keys'])
        except KeyError:raise NativeSnapshotIncomplete('Native recovery identity is incomplete') from None
        if any(value[field] is None for field in self.contract[table]['keys']):raise NativeSnapshotIncomplete('Native recovery identity is null')
        return result
    def extract(self,connection,*,schema,baseline):
        if connection.autocommit:raise NativeSnapshotIncomplete('Consistent transactional native snapshot required')
        if set(baseline)!=set(self.contract):raise NativeSnapshotIncomplete('Complete frozen source baseline required')
        result={table:{} for table in self.contract};old={table:{self.identity(table,row['raw']):row for row in rows} for table,rows in baseline.items()}
        with connection.cursor() as c:
            def query(target,where='',parameters=(),fields='data::text'):
                if target=='console_registry_approval_events':
                    c.execute('SELECT to_regclass(%s)',(schema+'.'+target,))
                    if c.fetchone()[0] is None:return []
                c.execute(sql.SQL('SELECT {} FROM {}.{} {}').format(sql.SQL(fields),sql.Identifier(schema),sql.Identifier(target),sql.SQL('WHERE '+where if where else '')),parameters)
                return c.fetchall()
            def add(table,raw,nulls=None):
                value=json.loads(raw);key=self.identity(table,raw);columns=[row[0] for row in self.contract[table]['columns']];missing=set(columns)-set(value)
                if any(nullable=='NO' and (name not in value or value[name] is None) for name,typ,udt,nullable in self.contract[table]['columns']):raise NativeSnapshotIncomplete('Native recovery row is missing required source fields: '+table)
                if nulls is None:
                    before=old[table].get(key);before_value=json.loads(before['raw']) if before else {};before_nulls=set(before['sql_null_fields']) if before else set()
                    nulls=[field for field in self.contract[table]['json_columns'] if field in missing or field in before_nulls and value.get(field) is None and before_value.get(field) is None]
                elif isinstance(nulls,str):nulls=json.loads(nulls)
                if set(nulls)-set(self.contract[table]['json_columns']):raise NativeSnapshotIncomplete('Native SQL-null metadata differs from source contract')
                c.execute("SELECT jsonb_object_agg(k,coalesce(v->k,'null'::jsonb))::text FROM unnest(%s::text[]) k CROSS JOIN (SELECT %s::jsonb v) p",(columns,raw));normalized=c.fetchone()[0]
                result[table][key]={'raw':normalized,'sql_null_fields':sorted(nulls)}
            def json_rows(table,target,where='',parameters=(),mask=False):
                for row in query(target,where,parameters,fields='data::text,json_null_fields::text' if mask else 'data::text'):add(table,row[0],row[1] if mask else None)
            for table in self.contract:
                if table in self.records:
                    kind,register,_=self.records[table];json_rows(table,'console_record_snapshots','kind=%s AND register_id=%s',(kind,register),True)
                elif table in SPECS or table in OPERATIONAL_SPECS:
                    spec=(SPECS if table in SPECS else OPERATIONAL_SPECS)[table];json_rows(table,spec['target'],'kind=%s',(spec['kind'],))
                elif table in self.structured:
                    spec=self.structured[table];json_rows(table,spec['target'],spec['kind_column']+'=%s',(spec['kind'],),spec['intake'])
                elif table in self.remaining:
                    family,key=self.remaining[table]
                    if family=='reference':json_rows(table,'native_registry_reference_data','kind=%s',(table,))
                    elif family=='import':json_rows(table,'console_registry_import_queue')
                    elif family=='import-history':json_rows(table,'native_registry_import_history')
                    else:
                        for raw, in query('console_register_definition_state',fields="(jsonb_build_object('register_id',id)||(data::jsonb->'schema'))::text",where="data::jsonb->'schema' IS NOT NULL AND data::jsonb->'schema'<>'null'::jsonb"):add(table,raw)
                elif table in self.auxiliary:
                    family,kind=self.auxiliary[table]
                    if family=='dedup':json_rows(table,'console_duplicate_matches','kind=%s',(kind,))
                    elif family=='document':json_rows(table,'console_document_catalog','kind=%s AND state=%s',(kind,'READY'))
                    elif family=='subscription':json_rows(table,'console_subscription_activity')
                    elif family=='operation' and kind=='export':json_rows(table,'console_registry_export_queue')
                    elif family=='operation':
                        for raw, in query('console_registry_operations','kind=%s',('event',)):
                            key=self.identity(table,raw);before=old[table].get(key)
                            if before:
                                c.execute('SELECT (%s::jsonb||%s::jsonb)::text',(before['raw'],raw));add(table,c.fetchone()[0])
                            else:
                                found=query('console_registry_approval_events','event_id=%s',(json.loads(raw)['event_id'],));full=found[0] if found else None
                                if not full:raise NativeSnapshotIncomplete('New approval event lacks full recovery payload')
                                add(table,full[0])
                        # Native callback events preserve fields deliberately
                        # excluded from the public summary (actor/request/error).
                        for raw, in query('console_registry_approval_events'):add(table,raw)
                    else:
                        target,rename={
                            'language':('console_languages',{'language_id':'id','language_code':'code','language_label':'label','language_flag_base64':'flag','is_default':'is_default','core_translation':'core','domain_translation':'domain'}),
                            'theme':('console_themes',{'theme_id':'id','theme_mnemonic':'name','is_factory_shipped':'factory'}),
                            'value':('console_theme_values',{'theme_value_id':'id','theme_id':'theme','attribute_name':'attribute','attribute_value':'value'}),
                            'configuration':('console_configuration',{'configuration_id':'id','registry_name':'name','registry_logo':'logo','registry_favicon':'favicon','registry_theme_id':'theme','registry_language_id':'language'})}[kind]
                        fields=sql.SQL('jsonb_build_object({})::text').format(sql.SQL(',').join(item for source,native in rename.items() for item in [sql.Literal(source),sql.Identifier(native)])).as_string(c)
                        for raw, in query(target,fields=fields):add(table,raw)
                else:
                    if self.identity_cipher is None:raise NativeSnapshotIncomplete('Identity recovery encryption key required')
                    kind='provider' if table.endswith('_providers') else 'attempt'
                    for ciphertext, in query('console_registrant_auth_secrets','kind=%s',(kind,),fields='ciphertext'):
                        raw=self.identity_cipher.decrypt(ciphertext.encode()).decode();value=json.loads(raw)
                        if kind=='provider' and value.get('client_private_key') and not value['client_private_key'].startswith('\\x'):
                            c.execute("SELECT jsonb_set(%s::jsonb,'{client_private_key}',to_jsonb(%s::text))::text",(raw,'\\x'+value['client_private_key'].encode().hex()));raw=c.fetchone()[0]
                        add(table,raw)
        return {table:list(values.values()) for table,values in result.items()}
