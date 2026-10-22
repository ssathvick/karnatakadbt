"""Ownership-gated identity recovery; no external action while source owns IAM."""
from sqlalchemy import text
from native_administration_ownership import AdministrationOwnership
from native_identity_recovery import RecoverableIdentityAdmin

class IdentityRecoveryWorker:
    def __init__(self,engine,key,admin_factory,*,allowed_prefix=None):
        self.engine,self.key,self.admin_factory,self.allowed_prefix=engine,key,admin_factory,allowed_prefix
        self.ownership=AdministrationOwnership(engine,'iam')
    def cycle(self):
        with self.engine.connect() as c:
            owner=c.execute(text("SELECT owner FROM kdbt_administration_control.ownership WHERE profile='iam'")).scalar_one()
        if owner!='NATIVE':return {'state':'BLOCKED','owner':owner,'committed':0,'compensated':0}
        with self.ownership.admission('NATIVE'):
            with self.engine.connect() as c:pending=c.execute(text("SELECT count(*) FROM kdbt_iam_identity_effects.intents WHERE state='PENDING'")).scalar_one()
            if not pending:return {'state':'RUNNING','owner':'NATIVE','committed':0,'compensated':0}
            adapter=RecoverableIdentityAdmin(self.engine,self.admin_factory(),self.key,allowed_prefix=self.allowed_prefix)
            result=adapter.reconcile()
            return {'state':'RUNNING','owner':'NATIVE',**result}
