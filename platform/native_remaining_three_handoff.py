"""Checkpointed handoff for process-local caches and irreversible native writes.

Runtime adapters must prove current fences, worker ownership and routing. This
module provides orchestration, not a production runtime adapter or admission.
Other completed service migrations continue to use their existing coordinator.
"""
from sqlalchemy import text
from native_worker_handoff import NativeWorkerHandoff, HandoffBlocked

FORWARD = ('fence_producers', 'stop_legacy_scheduler', 'drain_legacy_workers',
           'export_final_source_state', 'stop_legacy_workers', 'synchronize_final_state',
           'verify_native_state', 'start_native_workers', 'route_native', 'release_native_producers')
REVERSE = ('fence_producers', 'stop_native_scheduler', 'drain_native_workers',
           'stop_native_workers', 'export_final_native_state', 'reverse_native_writes',
           'restore_legacy_runtime', 'verify_legacy_state', 'route_legacy',
           'start_legacy_workers', 'release_legacy_producers')
REQUIRED = ('all_console_features_accepted', 'session_continuity_accepted',
            'external_callbacks_accepted', 'combined_recovery_accepted',
            'producer_fencing_accepted', 'restorable_backups_verified')


class RemainingThreeHandoff(NativeWorkerHandoff):
    def __init__(self, engine, scope, adapter):
        if not isinstance(scope, str) or not scope.startswith('remaining-three:'):
            raise ValueError('Dedicated remaining-three handoff scope required')
        super().__init__(engine, scope, adapter)

    def run(self, direction, *, generation, acceptance, stop_after=None):
        if direction not in {'forward', 'reverse'} or type(generation) is not int or generation < 1:
            raise ValueError('Explicit direction and positive generation required')
        if any(acceptance.get(name) is not True for name in REQUIRED):
            raise HandoffBlocked('Complete workflow, callback, combined recovery and fencing acceptance required')
        phases = FORWARD if direction == 'forward' else REVERSE
        if stop_after is not None and stop_after not in phases[:-1]:
            raise ValueError('Pause must precede writer release')
        with self.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as lock:
            key = 'native-worker-handoff:' + self.scope
            if not lock.execute(text('SELECT pg_try_advisory_lock(hashtextextended(:key,0))'), {'key': key}).scalar_one():
                raise HandoffBlocked('Another coordinator owns this scope')
            try:
                current = self.status()
                same = current is not None and current['generation'] == generation
                if current:
                    if generation < current['generation'] or (same and current['direction'] != direction):
                        raise HandoffBlocked('Stale or conflicting handoff generation')
                    if generation > current['generation'] and current['state'] != 'COMPLETE' and current['direction'] == direction:
                        raise HandoffBlocked('Reconcile the incomplete generation first')
                    if generation > current['generation'] and current['state'] == 'COMPLETE' and current['direction'] == direction:
                        raise HandoffBlocked('Ownership is already transferred in this direction; verify its existing generation')
                    if generation > current['generation'] and current['state'] != 'COMPLETE' and current['direction'] != direction:
                        needed = 'verify_native_state' if current['direction'] == 'forward' else 'verify_legacy_state'
                        if current['evidence'].get(needed, {}).get('verified') is not True:
                            raise HandoffBlocked('Unverified destination requires checkpoint abort recovery, not reverse copying')
                    if same and current['state'] == 'COMPLETE':
                        terminal = self._safe_evidence(self.adapter.observe_terminal(direction))
                        if terminal.get('verified') is not True:
                            raise HandoffBlocked('Completed ownership topology drifted; explicit reconciliation required')
                        return current
                evidence = current['evidence'] if same else {}
                start = 0
                if same:
                    if current['phase'] not in phases or current['state'] not in {'INTENT', 'BLOCKED', 'VERIFIED'}:
                        raise HandoffBlocked('Unknown handoff checkpoint')
                    start = phases.index(current['phase']) + (current['state'] == 'VERIFIED')
                safe = self._safe_evidence(self.adapter.observe_resume_safety(direction, generation, current))
                if safe.get('verified') is not True:
                    raise HandoffBlocked('Runtime ownership does not admit safe checkpoint reconciliation')
                for phase in phases[start:]:
                    lock.execute(text('SELECT 1'))
                    observed = self._safe_evidence(self.adapter.observe(phase))
                    record = dict(scope=self.scope, generation=generation, direction=direction,
                                  phase=phase, state='INTENT', evidence=evidence)
                    if observed.get('verified') is not True:
                        self._save(record)
                        try:
                            self.adapter.apply(phase)
                            lock.execute(text('SELECT 1'))
                            observed = self._safe_evidence(self.adapter.observe(phase))
                            if observed.get('verified') is not True:
                                raise HandoffBlocked('Phase did not reach observed state')
                        except Exception:
                            self._save({**record, 'state': 'BLOCKED'})
                            # Writer release can succeed before transport or
                            # journal failure. Do not claim the fence stayed shut.
                            raise HandoffBlocked('Handoff checkpoint blocked; reconcile observed ownership before continuing') from None
                    evidence = {**evidence, phase: observed}
                    self._save({**record, 'state': 'VERIFIED', 'evidence': evidence})
                    if phase == stop_after:
                        return self.status()
                terminal = self._safe_evidence(self.adapter.observe_terminal(direction))
                if terminal.get('verified') is not True:
                    raise HandoffBlocked('Final writer/worker ownership and routing are not verified')
                final = dict(scope=self.scope, generation=generation, direction=direction,
                             phase=phases[-1], state='COMPLETE', evidence={**evidence, 'terminal': terminal})
                self._save(final)
                return final
            finally:
                if not lock.invalidated:
                    lock.execute(text('SELECT pg_advisory_unlock(hashtextextended(:key,0))'), {'key': key})
