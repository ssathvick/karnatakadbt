"""Hold a shared ownership-row lock throughout each native dispatch tick."""
from contextlib import contextmanager
from sqlalchemy import select,text
from native_worker_handoff import handoffs,FORWARD


class RegistryWorkerAdmission:
    def __init__(self,engine,scope):
        if not scope:raise ValueError('Explicit registry handoff scope required')
        self.engine,self.scope=engine,scope

    @contextmanager
    def acquire(self):
        with self.engine.begin() as c:
            if c.execute(text("SELECT to_regclass('native_worker_handoffs')")).scalar_one() is None:
                yield False;return
            row=c.execute(select(handoffs).where(handoffs.c.scope==self.scope).with_for_update(read=True)).mappings().first()
            accepted=bool(row and row['direction']=='forward' and row['state']=='COMPLETE' and row['phase']=='release_native_producers' and all(row['evidence'].get(phase,{}).get('verified') is True for phase in FORWARD))
            yield accepted
