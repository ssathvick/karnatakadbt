"""Explicit database ownership for source shadows and native business producers."""
import re
from contextlib import contextmanager
from fastapi import HTTPException
from sqlalchemy import text


class NativeDomainOwnership:
    def __init__(self,engine,domain):
        if domain not in {'bank','bridge'}:raise ValueError('Explicit native payment domain required')
        self.engine,self.domain=engine,domain;self.schema='kdbt_'+domain+'_control';self.lock='karnatakadbt-'+domain+'-ownership'
    def initialize(self,source_id):
        with self.engine.begin() as c:
            c.execute(text('CREATE SCHEMA IF NOT EXISTS '+self.schema));c.execute(text('REVOKE ALL ON SCHEMA '+self.schema+' FROM PUBLIC'))
            c.execute(text('CREATE TABLE IF NOT EXISTS '+self.schema+".ownership(singleton boolean PRIMARY KEY CHECK(singleton),source_id uuid NOT NULL,owner text NOT NULL CHECK(owner IN ('SOURCE','NATIVE','FENCED')),generation bigint NOT NULL DEFAULT 0)"))
            c.execute(text('INSERT INTO '+self.schema+".ownership(singleton,source_id,owner) VALUES(true,:source,'SOURCE') ON CONFLICT DO NOTHING"),{'source':source_id})
            if str(c.execute(text('SELECT source_id FROM '+self.schema+'.ownership WHERE singleton')).scalar_one())!=source_id:raise ValueError('Native domain source identity differs')
    @contextmanager
    def admission(self,owner):
        if owner not in {'SOURCE','NATIVE'}:raise ValueError('Explicit producer admission required')
        with self.engine.begin() as c:
            c.execute(text('SELECT pg_advisory_xact_lock_shared(hashtextextended(:lock,0))'),{'lock':self.lock})
            current=c.execute(text('SELECT owner FROM '+self.schema+'.ownership WHERE singleton')).scalar_one()
            if current!=owner:raise HTTPException(503,'Payment domain producer ownership is fenced')
            yield
    def writer(self):return self.admission('NATIVE')
    def source_projection(self):return self.admission('SOURCE')
    @contextmanager
    def transition(self,expected,generation):
        """Compare-and-swap ownership only after every admitted producer exits.

        Both directions must pass through FENCED. The exclusive lock is the
        same key used by API, worker and source-projection admissions.
        """
        if expected not in {'SOURCE','NATIVE','FENCED'} or type(generation) is not int or generation<0:raise ValueError('Expected payment owner and generation required')
        with self.engine.begin() as c:
            c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:lock,0))'),{'lock':self.lock})
            current=c.execute(text('SELECT owner,generation FROM '+self.schema+'.ownership WHERE singleton FOR UPDATE')).one()
            if tuple(current)!=(expected,generation):raise ValueError('Stale payment ownership transition')
            changed=False
            def change(owner):
                nonlocal changed
                if changed or owner not in ({'SOURCE','NATIVE'} if expected=='FENCED' else {'FENCED'}):raise ValueError('Single fenced payment ownership transition required')
                c.execute(text('UPDATE '+self.schema+'.ownership SET owner=:owner,generation=generation+1 WHERE singleton'),{'owner':owner});changed=True
            yield change
