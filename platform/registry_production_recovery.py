"""Production-bound registry recovery admission across two fenced databases.

The coordinator pins database identities and the complete source contract,
requires a reverse handoff with observed quiescence, and holds both fence rows
against reopening until source replay commits. It never closes fences, grants
ownership, or infers acceptance. Ordinary rollback APIs remain clone-only.
"""
import hashlib,json
from contextlib import contextmanager
from psycopg2 import sql,extensions
from registry_producer_fence import LOCK,SCHEMA,authorize_recovery
from registry_change_journal import table_contract
from registry_reverse_journal import FullRegistryRollback
from native_worker_handoff import REVERSE

class RecoveryNotAdmitted(Exception):pass

def database_identity(connection):
    with connection.cursor() as c:
        c.execute('SELECT current_database(),(SELECT oid::text FROM pg_database WHERE datname=current_database()),system_identifier::text FROM pg_control_system()')
        name,oid,system=c.fetchone();return {'database':name,'database_oid':oid,'system_identifier':system}

def contract_digest(contract):return hashlib.sha256(json.dumps(contract,sort_keys=True,separators=(',',':')).encode()).hexdigest()

class RegistryProductionRecovery:
    def __init__(self,settings,source_contract,*,rehearsal=False):
        self.settings=dict(settings);self.contract=source_contract;self.rollback=FullRegistryRollback(source_contract)
        if settings['contract_digest']!=contract_digest(source_contract):raise ValueError('Pinned source recovery contract differs')
        source=settings['source_identity']['database'];native=settings['native_identity']['database']
        if rehearsal:
            if not source.startswith('kdbt_registry_ref_') or not native.startswith('kdbt_registry_ref_'):raise ValueError('Rehearsal requires two disposable reference databases')
        elif source!='register' or not native.startswith('kdbt_registry_candidate_'):raise ValueError('Explicit production registry database pair required')
        if settings['source_identity']==settings['native_identity'] or not settings.get('scope'):raise ValueError('Distinct source/native databases and handoff scope required')
    def _lock_fence(self,connection,expected,capability=None):
        with connection.cursor() as c:
            c.execute('SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))',(LOCK,))
            c.execute(sql.SQL('SELECT generation,owner,fenced,capability_hash FROM {}.control WHERE singleton FOR SHARE').format(sql.Identifier(SCHEMA)))
            row=c.fetchone()
            if not row or not row[2] or row[0]!=expected['generation'] or row[1]!=expected['owner']:raise RecoveryNotAdmitted('Recovery requires the expected durably closed producer fence')
            if capability is not None and hashlib.sha256(capability.encode()).hexdigest()!=row[3]:raise RecoveryNotAdmitted('Source recovery capability does not match the installed fence')
    @contextmanager
    def admission(self,source,native,*,source_fence,native_fence,capability):
        if source.autocommit or native.autocommit:raise RecoveryNotAdmitted('Two transactional database connections required')
        if any(c.get_transaction_status()!=extensions.TRANSACTION_STATUS_IDLE for c in [source,native]):raise RecoveryNotAdmitted('Fresh dedicated recovery connections required')
        # Source commits while the native fence and handoff locks remain held.
        # An exception rolls back the whole source replay, including receipts.
        with native:
            with source:
                for connection,expected in [(source,self.settings['source_identity']),(native,self.settings['native_identity'])]:
                    with connection.cursor() as c:c.execute("SET LOCAL lock_timeout='5s'");c.execute("SET LOCAL statement_timeout='60s'")
                    if database_identity(connection)!=expected:raise RecoveryNotAdmitted('Recovery database identity changed')
                self._lock_fence(native,native_fence)
                self._lock_fence(source,source_fence,capability)
                if source_fence['owner']!=native_fence['owner']:raise RecoveryNotAdmitted('Both producer fences must belong to the same recovery coordinator')
                with native.cursor() as c:
                    c.execute("SELECT generation,direction,phase,state,evidence FROM public.native_worker_handoffs WHERE scope=%s FOR SHARE",(self.settings['scope'],));handoff=c.fetchone()
                if not handoff or handoff[0]!=self.settings['handoff_generation'] or handoff[1]!='reverse' or handoff[2]!='reverse_native_writes' or handoff[3] not in {'INTENT','BLOCKED'}:raise RecoveryNotAdmitted('Verified reverse handoff must reach the reverse-write intent phase')
                for phase in REVERSE[:REVERSE.index('reverse_native_writes')]:
                    if handoff[4].get(phase,{}).get('verified') is not True:raise RecoveryNotAdmitted('Native producer/worker quiescence evidence is incomplete')
                if contract_digest(table_contract(source))!=self.settings['contract_digest']:raise RecoveryNotAdmitted('Production source schema changed after capture')
                authorize_recovery(source,capability)
                # Object recovery also acquires the exclusive ownership lock.
                # The source-authoritative object synchronizer holds it shared.
                with native.cursor() as c:c.execute("SELECT pg_advisory_xact_lock(hashtextextended('kdbt-registry-object-sync-ownership',0))")
                active=[True]
                def assert_admitted():
                    if not active[0] or any(c.get_transaction_status()!=extensions.TRANSACTION_STATUS_INTRANS for c in [source,native]):raise RecoveryNotAdmitted('Recovery admission is no longer active')
                try:yield assert_admitted
                finally:active[0]=False

    def recover(self,source,native,batches,*,source_fence,native_fence,capability):
        if not isinstance(batches,list) or not batches or any(not isinstance(row,dict) or not row.get('operation_id') or not row.get('changes') for row in batches):raise ValueError('Explicit complete recovery batches required')
        with self.admission(source,native,source_fence=source_fence,native_fence=native_fence,capability=capability):
            outcomes=[]
            for batch in batches:outcomes.append(self.rollback._apply_transaction(source,batch['operation_id'],batch['changes']))
        return {'batches':len(outcomes),'changes':sum(row['changes'] for row in outcomes),'skipped_batches':sum(row['skipped'] for row in outcomes)}
