"""Shared producer admission for IAM, consent and partner SQL shadows."""
import uuid
from contextlib import contextmanager
from sqlalchemy import text

class AdministrationOwnership:
    def __init__(self,engine,profile):
        if profile not in {'iam','consent','partner'}:raise ValueError('Explicit administration profile required')
        self.engine,self.profile=engine,profile;self.lock='karnatakadbt-administration-ownership:'+profile
    def initialize(self,source_id):
        source_id=str(uuid.UUID(source_id))
        with self.engine.begin() as c:
            c.execute(text('CREATE SCHEMA IF NOT EXISTS kdbt_administration_control'))
            c.execute(text('REVOKE ALL ON SCHEMA kdbt_administration_control FROM PUBLIC'))
            c.execute(text("CREATE TABLE IF NOT EXISTS kdbt_administration_control.ownership(profile text PRIMARY KEY,source_id uuid NOT NULL,owner text NOT NULL CHECK(owner IN ('SOURCE','NATIVE','FENCED')),generation bigint NOT NULL DEFAULT 0)"))
            c.execute(text("INSERT INTO kdbt_administration_control.ownership(profile,source_id,owner) VALUES(:profile,:source,'SOURCE') ON CONFLICT DO NOTHING"),{'profile':self.profile,'source':source_id})
            if str(c.execute(text('SELECT source_id FROM kdbt_administration_control.ownership WHERE profile=:profile'),{'profile':self.profile}).scalar_one())!=source_id:raise ValueError('Administration source identity differs')
    @contextmanager
    def admission(self,owner):
        if owner not in {'SOURCE','NATIVE'}:raise ValueError('Explicit producer ownership required')
        with self.engine.begin() as c:
            c.execute(text('SELECT pg_advisory_xact_lock_shared(hashtextextended(:lock,0))'),{'lock':self.lock})
            current=c.execute(text('SELECT owner FROM kdbt_administration_control.ownership WHERE profile=:profile'),{'profile':self.profile}).scalar_one()
            if current!=owner:raise ValueError('Administration producer ownership is fenced')
            yield
    @contextmanager
    def transition(self,expected,generation):
        if expected not in {'SOURCE','NATIVE','FENCED'} or type(generation) is not int or generation<0:raise ValueError('Expected owner and generation required')
        with self.engine.begin() as c:
            c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:lock,0))'),{'lock':self.lock})
            current=c.execute(text('SELECT owner,generation FROM kdbt_administration_control.ownership WHERE profile=:profile FOR UPDATE'),{'profile':self.profile}).one()
            if tuple(current)!=(expected,generation):raise ValueError('Stale administration ownership transition')
            changed=False
            def set_owner(value):
                nonlocal changed
                if changed or value not in ({'SOURCE','NATIVE'} if expected=='FENCED' else {'FENCED'}):raise ValueError('Single fenced ownership transition required')
                c.execute(text('UPDATE kdbt_administration_control.ownership SET owner=:owner,generation=generation+1 WHERE profile=:profile'),{'owner':value,'profile':self.profile})
                changed=True
            yield set_owner

@contextmanager
def source_projection_guard(connection,profile,source_id):
    """Hold a session lock across destination commits and source acknowledgements."""
    if profile not in {'iam','consent','partner'}:raise ValueError('Explicit source projection profile required')
    lock='karnatakadbt-administration-ownership:'+profile;held=False
    try:
        with connection.cursor() as c:
            c.execute('SELECT pg_advisory_lock_shared(hashtextextended(%s,0))',(lock,));held=True
            c.execute('SELECT owner,source_id::text FROM kdbt_administration_control.ownership WHERE profile=%s',(profile,));row=c.fetchone()
            if row is None or row[1]!=source_id:raise ValueError('Pinned administration source control required')
        connection.commit()
        yield row[0]=='SOURCE'
    finally:
        connection.rollback()
        if held:
            with connection.cursor() as c:c.execute('SELECT pg_advisory_unlock_shared(hashtextextended(%s,0))',(lock,))
            connection.commit()
