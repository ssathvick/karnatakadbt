"""Pinned, fenced SQL recovery for IAM, consent and partner administration.

Keycloak, notifications and approval side effects require their own recovery
admission. This class restores database transactions and synchronization only.
"""
import json
from contextlib import contextmanager
import registry_producer_fence as fence
from registry_change_journal import table_contract
from native_payment_recovery import NativePaymentRecovery,identity

class NativeAdministrationRecovery(NativePaymentRecovery):
    def __init__(self,source,native,settings,*,profile,source_fence,native_fence):
        if profile not in {'iam','consent','partner'}:raise ValueError('Explicit administration recovery profile required')
        if settings.get('mirror_schema')!='administration_live_mirror':raise ValueError('Pinned administration mirror required')
        self.domain=profile;self.ownership_lock='karnatakadbt-administration-ownership:'+profile
        self.source,self.native,self.settings=source,native,settings;self.expected_source,self.expected_native=source_fence,native_fence;self.admitted=False
    @contextmanager
    def admission(self):
        if self.source.autocommit or self.native.autocommit:raise ValueError('Transactional administration recovery required')
        for connection,expected in [(self.source,self.settings['source_identity']),(self.native,self.settings['native_identity'])]:
            if identity(connection)!=expected:raise ValueError('Administration recovery database identity differs')
            if json.loads(json.dumps(table_contract(connection)))!=self.settings['contract']:raise ValueError('Administration recovery table contract differs')
        held=[]
        with self.native.cursor() as c:c.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',(self.ownership_lock,))
        try:
            with self.native.cursor() as c:
                c.execute('SELECT owner,source_id::text FROM kdbt_administration_control.ownership WHERE profile=%s',(self.domain,));row=c.fetchone()
                if row is None or row[0]!='FENCED' or row[1]!=self.settings['source_id']:raise ValueError('Pinned administration ownership must be FENCED')
            for connection,expected in [(self.source,self.expected_source),(self.native,self.expected_native)]:
                with connection.cursor() as c:c.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',(fence.LOCK,))
                held.append(connection)
                if expected.get('fenced') is not True or fence.state(connection)!=expected:raise ValueError('Exact closed administration SQL producer fences required')
            self.admitted=True;yield self
        finally:
            self.admitted=False;self.source.rollback();self.native.rollback()
            for connection in reversed(held):
                with connection.cursor() as c:c.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(fence.LOCK,))
                connection.commit()
            with self.native.cursor() as c:c.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(self.ownership_lock,))
            self.native.commit()
