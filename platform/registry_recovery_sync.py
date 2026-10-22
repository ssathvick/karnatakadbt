"""Reconcile recovered native state before source-authoritative sync resumes.

Both producers must remain fenced. Verify all source families against the
native inverse snapshot before refreshing any projection/cache. Destination
receipts commit before source acknowledgements, matching ordinary sync's
crash-recovery protocol. Native-only worker/audit tables are retained.
"""
import hashlib,json
from psycopg2 import sql
from registry_native_snapshot import NativeRegistrySnapshot
from registry_change_journal import source_identity,put_mirror_row,SCHEMA
from registry_record_sync import NativeRecordProjector
from registry_json_sync import NativeJsonProjector
from registry_operational_sync import NativeOperationalProjector
from registry_structured_sync import NativeStructuredProjector
from registry_auxiliary_sync import NativeAuxiliaryProjector
from registry_remaining_sync import NativeRemainingProjector
from registry_identity_sync import NativeIdentityProjector
from registry_producer_fence import authorize_recovery


class RegistryRecoverySync:
    def __init__(self,coordinator,*,identity_key,mirror_schema,native_schema='public'):
        self.coordinator=coordinator;self.contract=coordinator.contract
        self.mirror,self.schema=mirror_schema,native_schema
        self.snapshot=NativeRegistrySnapshot(self.contract,identity_key=identity_key)
        self.adapters=[NativeRecordProjector(native_schema),NativeJsonProjector(native_schema),NativeOperationalProjector(native_schema),NativeStructuredProjector(native_schema),NativeAuxiliaryProjector(native_schema),NativeRemainingProjector(native_schema),NativeIdentityProjector(native_schema,encryption_key=identity_key)]

    def adopt(self,source,native,*,native_capability,capture_key,**admission):
        # Admission owns both transaction commits. Source acknowledgement is
        # deliberately a separate transaction after destination commit.
        with self.coordinator.admission(source,native,**admission):
            authorize_recovery(native,native_capability)
            with native.cursor() as c:
                c.execute("SELECT set_config('kdbt.native_capture_key',%s,true)",(capture_key,))
                c.execute("SELECT set_config('kdbt.native_capture_writer','source-sync',true)")
            result=self._refresh(source,native)
        self._acknowledge(source,native,result['source_id'])
        return {k:v for k,v in result.items() if k!='source_id'}

    def _refresh(self,source,native):
        identity,contract=source_identity(source)
        if json.loads(json.dumps(contract))!=json.loads(json.dumps(self.contract)):raise ValueError('Recovery synchronization contract differs')
        baseline={table:[] for table in contract};current={table:[] for table in contract}
        with native.cursor() as c:
            c.execute(sql.SQL('SELECT 1 FROM {}.state WHERE source_id=%s').format(sql.Identifier(self.mirror)),(identity,))
            if not c.fetchone():raise ValueError('Matching frozen source mirror required')
            c.execute(sql.SQL('SELECT table_name,data::text,sql_null_fields FROM {}.rows WHERE source_id=%s').format(sql.Identifier(self.mirror)),(identity,))
            for table,raw,nulls in c.fetchall():baseline[table].append({'raw':raw,'sql_null_fields':nulls})
        reconstructed=self.snapshot.extract(native,schema=self.schema,baseline=baseline)
        # PostgreSQL types normalize timestamps/UUIDs without rounding JSON
        # decimal payloads through Python. SQL/JSON NULL masks remain explicit.
        with source.cursor() as c:
            for table,profile in contract.items():
                fields=sql.SQL(',').join(sql.SQL('CASE WHEN t.{} IS NULL THEN {} END').format(sql.Identifier(field),sql.Literal(field)) for field in profile['json_columns'])
                c.execute(sql.SQL('SELECT to_jsonb(t)::text,array_remove(ARRAY[{}]::text[],NULL) FROM public.{} t').format(fields,sql.Identifier(table)))
                current[table]=[{'raw':raw,'sql_null_fields':flags} for raw,flags in c.fetchall()]
                expected={self.snapshot.identity(table,row['raw']):row for row in current[table]}
                actual={self.snapshot.identity(table,row['raw']):row for row in reconstructed[table]}
                if set(expected)!=set(actual):raise ValueError('Recovered source/native identities differ: '+table)
                for key,row in expected.items():
                    candidate=actual[key]
                    c.execute(sql.SQL('SELECT to_jsonb(r)=%s::jsonb FROM jsonb_populate_record(NULL::public.{},%s::jsonb) r').format(sql.Identifier(table)),(row['raw'],candidate['raw']))
                    if not c.fetchone()[0] or sorted(row['sql_null_fields'])!=sorted(candidate['sql_null_fields']):raise ValueError('Recovered source/native values differ: '+table)
        # Only exact, fully recovered state reaches this point. Rebuild sync
        # metadata and canonical source projections, preserving native-only
        # receipts/outboxes. Do not replay old before images over native writes.
        with native.cursor() as c:
            for table in ['native_record_sync_state','native_json_sync_state','native_auxiliary_sync_state']:
                c.execute(sql.SQL('DELETE FROM {}.{}').format(sql.Identifier(self.schema),sql.Identifier(table)))
            c.execute(sql.SQL('DELETE FROM {}.rows WHERE source_id=%s').format(sql.Identifier(self.mirror)),(identity,))
            for table,rows in current.items():
                for row in rows:put_mirror_row(c,self.mirror,identity,table,contract[table]['keys'],row['raw'],row['sql_null_fields'])
            for adapter in self.adapters:
                for table in adapter.mapping:
                    for row in current[table]:
                        raw,nulls=row['raw'],row['sql_null_fields']
                        if isinstance(adapter,NativeAuxiliaryProjector):
                            for output in adapter.outputs(c,table,raw):adapter.put_output(c,output)
                            c.execute(sql.SQL('INSERT INTO {}.native_auxiliary_sync_state VALUES(%s,%s,%s)').format(sql.Identifier(self.schema)),(table,adapter.source_key(table,raw),adapter.encode_state(raw)))
                        else:
                            key=adapter.key(table,raw);fingerprint=adapter.fingerprint(c,table,key)
                            state='native_record_sync_state' if isinstance(adapter,NativeRecordProjector) else 'native_json_sync_state'
                            if fingerprint is not None:c.execute(sql.SQL('INSERT INTO {}.{} VALUES(%s,%s,%s)').format(sql.Identifier(self.schema),sql.Identifier(state)),(table,key,fingerprint))
                            if isinstance(adapter,(NativeRecordProjector,NativeStructuredProjector)):adapter.put(c,table,raw,nulls)
                            else:adapter.put(c,table,raw)
            with source.cursor() as sc:
                sc.execute(sql.SQL('SELECT event_id,transaction_id,table_name,operation,before_row::text,after_row::text,sql_null_fields FROM {}.events ORDER BY event_id').format(sql.Identifier(SCHEMA)))
                for event_id,tx,table,operation,before,after,nulls in sc.fetchall():
                    digest=hashlib.sha256(json.dumps([table,operation,before,after,nulls],separators=(',',':')).encode()).hexdigest()
                    c.execute(sql.SQL('SELECT digest FROM {}.receipts WHERE source_id=%s AND event_id=%s').format(sql.Identifier(self.mirror)),(identity,event_id));old=c.fetchone()
                    if old and old[0]!=digest:raise ValueError('Recovery synchronization receipt changed')
                    if not old:c.execute(sql.SQL('INSERT INTO {}.receipts VALUES(%s,%s,%s,%s)').format(sql.Identifier(self.mirror)),(identity,event_id,tx,digest))
        return {'source_id':identity,'tables':len(contract),'rows':sum(len(rows) for rows in current.values())}

    def _acknowledge(self,source,native,identity):
        # The normal reconciler handles a crash here: committed destination
        # receipts make the pending source events safely retryable.
        with source,source.cursor() as sc,native.cursor() as c:
            c.execute(sql.SQL('SELECT event_id FROM {}.receipts WHERE source_id=%s').format(sql.Identifier(self.mirror)),(identity,));ids=[row[0] for row in c.fetchall()]
            sc.execute(sql.SQL('UPDATE {}.events SET acknowledged=true WHERE event_id=ANY(%s)').format(sql.Identifier(SCHEMA)),(ids,))
        native.commit()
