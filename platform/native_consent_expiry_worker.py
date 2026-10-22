"""Ownership-gated consent expiry with atomic audit and bounded row locking."""
import uuid
from sqlalchemy import MetaData,Table,select,update,text
from native_administration_ownership import AdministrationOwnership
from native_consent_policy import now

class NativeConsentExpiryWorker:
    def __init__(self,engine):
        self.engine=engine;self.ownership=AdministrationOwnership(engine,'consent');metadata=MetaData()
        self.artefacts=Table('consent_artefacts',metadata,schema='public',autoload_with=engine);self.audits=Table('audit_logs',metadata,schema='public',autoload_with=engine)
    def cycle(self,limit=500):
        if type(limit) is not int or not 1<=limit<=1000:raise ValueError('Bounded consent expiry batch required')
        with self.ownership.admission('NATIVE'),self.engine.begin() as c:
            c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('karnatakadbt-native-consent-policy',0))"));stamp=now()
            rows=c.execute(select(self.artefacts.c.id).where(self.artefacts.c.status=='active',self.artefacts.c.valid_until<stamp).order_by(self.artefacts.c.id).limit(limit).with_for_update(skip_locked=True)).scalars().all()
            for identifier in rows:
                c.execute(update(self.artefacts).where(self.artefacts.c.id==identifier).values(status='expired',expired_at=stamp,updated_at=stamp))
                c.execute(self.audits.insert().values(id=str(uuid.uuid4()),created_at=stamp,updated_at=stamp,entity_type='consent',entity_id=identifier,action='consent.expired',actor='native-expiration',details={}))
            return len(rows)
