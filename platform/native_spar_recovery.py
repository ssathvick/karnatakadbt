"""Pinned, fenced reverse recovery for the five financial-address tables.

This does not change routes or grant ownership. The handoff coordinator must
close both SQL fences and set FENCED ownership before admitting recovery.
"""
import hashlib,json
from contextlib import contextmanager
from psycopg2 import sql
import registry_producer_fence as fence
from registry_record_rollback import RecordRollback
from registry_change_journal import table_contract,put_mirror_row
from administration_table_sync import AdministrationTableProjector
from native_spar_ownership import LOCK


def identity(connection):
    with connection.cursor() as c:
        c.execute('SELECT current_database(),(SELECT oid::text FROM pg_database WHERE datname=current_database()),system_identifier::text FROM pg_control_system()')
        return dict(zip(['database','database_oid','system_identifier'],c.fetchone()))


def rollback_engine(contract):
    engine=RecordRollback({'mapping':{}})
    engine.mapping={name:{'primary_key':meta['keys'],'columns':{column[0]:{'type':column[1]} for column in meta['columns']}} for name,meta in contract.items()}
    return engine


class NativeSparRecovery:
    def __init__(self,source,native,settings,*,source_fence,native_fence):
        self.source,self.native,self.settings=source,native,settings
        self.expected_source,self.expected_native=source_fence,native_fence
        self.admitted=False

    @contextmanager
    def admission(self):
        if self.source.autocommit or self.native.autocommit:raise ValueError('Transactional mapping recovery required')
        for connection,expected in [(self.source,self.settings['source_identity']),(self.native,self.settings['native_identity'])]:
            if identity(connection)!=expected:raise ValueError('Mapping recovery database identity differs')
            if json.loads(json.dumps(table_contract(connection)))!=self.settings['contract']:raise ValueError('Mapping recovery table contract differs')
        with self.native.cursor() as c:c.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',(LOCK,))
        held=[]
        try:
            with self.native.cursor() as c:
                c.execute('SELECT owner FROM kdbt_spar_control.ownership WHERE singleton')
                if c.fetchone()[0]!='FENCED':raise ValueError('Mapping ownership must be FENCED for reverse recovery')
            for connection,expected in [(self.source,self.expected_source),(self.native,self.expected_native)]:
                with connection.cursor() as c:c.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',(fence.LOCK,))
                held.append(connection)
                if expected.get('fenced') is not True or fence.state(connection)!=expected:raise ValueError('Expected closed mapping producer fence required')
            self.admitted=True
            yield self
        finally:
            self.admitted=False
            self.source.rollback();self.native.rollback()
            for connection in reversed(held):
                with connection.cursor() as c:c.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(fence.LOCK,))
                connection.commit()
            with self.native.cursor() as c:c.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(LOCK,))
            self.native.commit()

    def restore_native_transactions(self):
        if not self.admitted:raise ValueError('Fenced mapping recovery admission required')
        schema=self.settings['capture_schema'];crypto=self.settings['crypto_schema'];groups={}
        with self.native.cursor() as c:
            # PostgreSQL retains arbitrary JSON numeric precision. Only strings
            # and null-mask arrays cross into Python, never parsed row values.
            query=sql.SQL('''WITH frames AS (SELECT sequence,transaction_id,table_name,operation,
                {}.pgp_sym_decrypt(ciphertext,%s)::jsonb AS frame FROM {}.events)
                SELECT sequence,transaction_id,table_name,operation,
                CASE WHEN frame->'before'='null'::jsonb THEN NULL ELSE (frame->'before')::text END,
                CASE WHEN frame->'after'='null'::jsonb THEN NULL ELSE (frame->'after')::text END,
                ARRAY(SELECT jsonb_array_elements_text(frame->'before_sql_null_fields')),
                ARRAY(SELECT jsonb_array_elements_text(frame->'after_sql_null_fields')) FROM frames ORDER BY sequence''').format(sql.Identifier(crypto),sql.Identifier(schema))
            c.execute(query,(self.settings['capture_key'],))
            for sequence,tx,table,operation,before,after,before_nulls,after_nulls in c.fetchall():
                if operation not in {'INSERT','UPDATE','DELETE'}:raise ValueError('Unsupported mapping recovery operation')
                groups.setdefault(tx,[]).append({'table':table,'before':before,'after':after,'before_sql_null_fields':before_nulls,'after_sql_null_fields':after_nulls})
        engine=rollback_engine(self.settings['contract']);changes=0;skipped=0
        for tx,rows in groups.items():
            fence.authorize_recovery(self.source,self.settings['source_capability'])
            result=engine._apply_transaction(self.source,'spar-'+self.settings['native_identity']['database_oid']+'-'+tx,rows)
            self.source.commit();changes+=result['changes'];skipped+=int(result['skipped'])
        AdministrationTableProjector(self.settings['contract']).sequences(self.native,self.source);self.source.commit()
        return {'transactions':len(groups),'changes':changes,'already_restored_transactions':skipped}

    def align_forward_synchronization(self,source_id):
        if not self.admitted:raise ValueError('Fenced mapping recovery admission required')
        mirror='kdbt_spar_mirror';captured=[]
        with self.source.cursor() as s,self.native.cursor() as n:
            # Both database fences remain closed. Check every column, row and
            # SQL-null distinction before recording any recovered receipt.
            all_rows={}
            for table,meta in self.settings['contract'].items():
                nulls=sql.SQL('ARRAY[{}]::text[]').format(sql.SQL(',').join(sql.SQL('CASE WHEN t.{} IS NULL THEN {} END').format(sql.Identifier(field),sql.Literal(field)) for field in meta['json_columns']))
                query=sql.SQL('SELECT to_jsonb(t)::text,array_remove({},NULL) FROM public.{} t ORDER BY {}').format(nulls,sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,meta['keys'])))
                s.execute(query);source_rows=s.fetchall();n.execute(query);native_rows=n.fetchall()
                if source_rows!=native_rows:raise ValueError('Full mapping row reconciliation required before synchronization restart')
                all_rows[table]=source_rows
            n.execute('DELETE FROM kdbt_spar_mirror.rows WHERE source_id=%s',(source_id,))
            for table,rows in all_rows.items():
                for raw,null_fields in rows:put_mirror_row(n,mirror,source_id,table,self.settings['contract'][table]['keys'],raw,null_fields)
            s.execute('SELECT event_id,transaction_id,table_name,operation,before_row::text,after_row::text,sql_null_fields FROM kdbt_migration_capture.events WHERE NOT acknowledged ORDER BY event_id')
            for event_id,tx,table,operation,before,after,null_fields in s.fetchall():
                digest=hashlib.sha256(json.dumps([table,operation,before,after,null_fields],separators=(',',':')).encode()).hexdigest()
                n.execute('SELECT digest FROM kdbt_spar_mirror.receipts WHERE source_id=%s AND event_id=%s',(source_id,event_id));old=n.fetchone()
                if old and old[0]!=digest:raise ValueError('Recovered mapping receipt differs')
                if not old:n.execute('INSERT INTO kdbt_spar_mirror.receipts VALUES(%s,%s,%s,%s)',(source_id,event_id,tx,digest))
                captured.append(event_id)
            self.native.commit()
            if captured:s.execute('UPDATE kdbt_migration_capture.events SET acknowledged=true WHERE event_id=ANY(%s)',(captured,))
            self.source.commit()
        return {'tables_reconciled':len(all_rows),'recovered_source_receipts':len(captured)}
