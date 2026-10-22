"""Database-backed account-mapping admission shared by API and handoff tools."""
from contextlib import contextmanager
from fastapi import HTTPException
from sqlalchemy import text

LOCK='karnatakadbt-account-mapping-ownership'

class NativeSparOwnership:
    def __init__(self,engine):self.engine=engine

    def initialize(self,source_id):
        with self.engine.begin() as c:
            c.execute(text('CREATE SCHEMA IF NOT EXISTS kdbt_spar_control'))
            c.execute(text('REVOKE ALL ON SCHEMA kdbt_spar_control FROM PUBLIC'))
            c.execute(text("CREATE TABLE IF NOT EXISTS kdbt_spar_control.ownership(singleton boolean PRIMARY KEY CHECK(singleton),source_id uuid NOT NULL,owner text NOT NULL CHECK(owner IN ('SOURCE','NATIVE','FENCED')),generation bigint NOT NULL DEFAULT 0)"))
            c.execute(text("INSERT INTO kdbt_spar_control.ownership(singleton,source_id,owner) VALUES(true,:source,'SOURCE') ON CONFLICT(singleton) DO NOTHING"),{'source':source_id})
            if str(c.execute(text('SELECT source_id FROM kdbt_spar_control.ownership WHERE singleton')).scalar_one())!=source_id:raise ValueError('Mapping source identity differs')

    @contextmanager
    def writer(self):
        with self.engine.begin() as c:
            c.execute(text('SELECT pg_advisory_xact_lock_shared(hashtextextended(:lock,0))'),{'lock':LOCK})
            owner=c.execute(text('SELECT owner FROM kdbt_spar_control.ownership WHERE singleton')).scalar_one()
            if owner!='NATIVE':raise HTTPException(503,'Native account-mapping writer remains in standby')
            yield

    @contextmanager
    def source_projection(self):
        with self.engine.begin() as c:
            c.execute(text('SELECT pg_advisory_xact_lock_shared(hashtextextended(:lock,0))'),{'lock':LOCK})
            owner=c.execute(text('SELECT owner FROM kdbt_spar_control.ownership WHERE singleton')).scalar_one()
            if owner!='SOURCE':raise ValueError('Source projection is fenced during native ownership')
            yield
