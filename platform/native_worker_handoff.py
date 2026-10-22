"""Durable, fenced worker handoff and reverse handoff orchestration.

Each configured operation must be idempotent and verified from observed runtime
state. A crash leaves an intent record; replay reconciles that operation before
advancing. No failed/unknown phase implicitly restarts legacy consumers.
Production adapters must also fence portal SQL writers and external producers.
"""
import json
from sqlalchemy import MetaData, Table, Column, String, Integer, select, text
from sqlalchemy.dialects.postgresql import JSONB, insert

metadata=MetaData()
handoffs=Table('native_worker_handoffs',metadata,
    Column('scope',String,primary_key=True),Column('generation',Integer,nullable=False),
    Column('direction',String,nullable=False),Column('phase',String,nullable=False),
    Column('state',String,nullable=False),Column('evidence',JSONB,nullable=False))

FORWARD=('fence_producers','stop_legacy_scheduler','drain_legacy_workers','stop_legacy_workers',
         'synchronize_final_state','verify_native_state','start_native_workers','route_native','release_native_producers')
REVERSE=('fence_producers','stop_native_scheduler','drain_native_workers','stop_native_workers',
         'reverse_native_writes','verify_legacy_state','route_legacy','start_legacy_workers','release_legacy_producers')
REQUIRED=('all_console_features_accepted','session_continuity_accepted','external_callbacks_accepted',
          'reverse_projection_accepted','queue_recovery_accepted','producer_fencing_accepted')


class HandoffBlocked(Exception):
    pass


class NativeWorkerHandoff:
    def __init__(self, engine, scope, adapter):
        if not isinstance(scope,str) or not scope or len(scope)>128:
            raise ValueError('Explicit bounded handoff scope required')
        self.engine,self.scope,self.adapter=engine,scope,adapter

    def initialize(self):
        metadata.create_all(self.engine)

    def status(self):
        with self.engine.connect() as c:
            value=c.execute(select(handoffs).where(handoffs.c.scope==self.scope)).mappings().first()
            return dict(value) if value else None

    def _save(self, value):
        # Deliberately uses an independent committed connection: intent must
        # survive a process death while an external deployment action runs.
        with self.engine.begin() as c:
            c.execute(insert(handoffs).values(**value).on_conflict_do_update(index_elements=['scope'],set_=value))

    @staticmethod
    def _safe_evidence(value):
        # Evidence contains predicates/counts only, never tokens or job payloads.
        if not isinstance(value,dict) or any(not isinstance(k,str) or not isinstance(v,(bool,int)) for k,v in value.items()):
            raise HandoffBlocked('Adapter must return boolean/count evidence')
        return value

    def run(self,direction,*,generation,acceptance,stop_after=None):
        if direction not in {'forward','reverse'} or not isinstance(generation,int) or generation<1:
            raise ValueError('Explicit direction and positive generation required')
        if any(acceptance.get(name) is not True for name in REQUIRED):
            raise HandoffBlocked('Feature, identity, recovery and producer-fence acceptance required')
        phases=FORWARD if direction=='forward' else REVERSE
        if stop_after is not None and stop_after not in phases[:-1]:raise ValueError('Pause must precede final producer release')
        with self.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as lock:
            key='native-worker-handoff:'+self.scope
            if not lock.execute(text('SELECT pg_try_advisory_lock(hashtextextended(:key,0))'),{'key':key}).scalar_one():
                raise HandoffBlocked('Another coordinator holds the handoff scope')
            try:
                current=self.status()
                if current:
                    if generation<current['generation']:
                        raise HandoffBlocked('Stale handoff generation')
                    if generation==current['generation'] and direction!=current['direction']:
                        raise HandoffBlocked('Reverse handoff requires a new generation')
                    if generation>current['generation'] and current['state']!='COMPLETE' and direction==current['direction']:
                        raise HandoffBlocked('Unfinished handoff must reconcile before a new attempt')
                    if generation==current['generation'] and current['state']=='COMPLETE':
                        return current
                evidence=current['evidence'] if current and generation==current['generation'] else {}
                for phase in phases:
                    lock.execute(text('SELECT 1'))
                    # Even completed phases are re-observed after restart.
                    # Receipts cannot conceal a restarted legacy consumer.
                    observed=self._safe_evidence(self.adapter.observe(phase))
                    if observed.get('verified') is not True:
                        record=dict(scope=self.scope,generation=generation,direction=direction,phase=phase,state='INTENT',evidence=evidence)
                        self._save(record)
                        lock.execute(text('SELECT 1'))
                        try:
                            self.adapter.apply(phase)
                            lock.execute(text('SELECT 1'))
                            observed=self._safe_evidence(self.adapter.observe(phase))
                            if observed.get('verified') is not True:
                                raise HandoffBlocked('Handoff phase did not reach verified state')
                        except Exception:
                            self._save({**record,'state':'BLOCKED'})
                            raise HandoffBlocked('Handoff phase blocked; producers remain fenced') from None
                    evidence={**evidence,phase:observed}
                    self._save(dict(scope=self.scope,generation=generation,direction=direction,phase=phase,state='VERIFIED',evidence=evidence))
                    if phase==stop_after:
                        # The generation remains incomplete and writer admission
                        # stays closed until all coordinated domains can resume.
                        return self.status()
                final=dict(scope=self.scope,generation=generation,direction=direction,phase=phases[-1],state='COMPLETE',evidence=evidence)
                self._save(final)
                return final
            finally:
                if not lock.invalidated:
                    lock.execute(text('SELECT pg_advisory_unlock(hashtextextended(:key,0))'),{'key':key})
