"""Unified native registry runtime with explicit authority and single leadership.

The caller supplies a configured registry store and approved network clients.
No runtime silently adopts a staff user's identity or falls back to broad access.
"""
import datetime
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from sqlalchemy import text
from registry_worker_dispatch import NativeRegistryDispatcher, TASKS, intervals_from_settings
from registry_native_workers import NativeRegistryWorkers, TASKS as identifier_tasks
from registry_dedup_workers import NativeDedupWorkers, TASK_KINDS
from registry_outgoing_workers import NativeOutgoingWorkers, TASKS as outgoing_tasks
from registry_ingestion_workers import NativeIngestionWorkers, TASKS as incoming_tasks
from registry_pipeline_workers import NativePipelineWorkers, TASKS as pipeline_tasks
from registry_export_worker import NativeExportWorker
from registry_import_worker import NativeImportWorker
from registry_score_worker import NativeScoreWorker
from registry_intake_ingest_worker import NativeIntakeIngestWorker


class IdentifierHttpClient:
    def __init__(self, endpoint, allowed_origins, types, transport=None):
        parsed=urlsplit(endpoint)
        if (parsed.scheme+'://'+parsed.netloc not in allowed_origins or
                parsed.scheme not in {'http','https'} or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('Explicit identifier origin required')
        if not types or any(not isinstance(k,str) or not isinstance(v,str) or not v for k,v in types.items()):
            raise ValueError('Explicit register-to-identifier type mapping required')
        self.endpoint,self.types,self.transport=endpoint.rstrip('/'),dict(types),transport

    def __call__(self, mnemonic):
        kind=self.types.get(mnemonic)
        if kind is None:raise ValueError('Identifier type is not configured')
        with httpx.Client(timeout=15,trust_env=False,follow_redirects=False,transport=self.transport) as client:
            response=client.post(self.endpoint+'/v1/idgenerator/'+quote(kind,safe='')+'/id')
            response.raise_for_status()
            body=response.json()
        value=(body.get('response') or {}).get('id')
        if body.get('errors') or not isinstance(value,str) or not value.isascii() or not value.isdecimal() or len(value)>32:
            raise ValueError('Identifier service did not return decimal digits')
        return value


def assemble_workers(store, *, principal_provider, allocate_identifier, websub,
                     import_sender, import_signature, settings=None, jsonld_loader=None):
    if not all(callable(x) for x in [principal_provider,allocate_identifier,websub]):
        raise ValueError('Worker authority, identifier service and WebSub service are required')
    if not import_sender or not import_signature:
        raise ValueError('Explicit import envelope credentials required')
    settings=settings or {}
    handlers={}
    def add(tasks, worker):
        if handlers.keys() & set(tasks):raise ValueError('Duplicate native task handler')
        initialize=getattr(worker,'initialize',None)
        if initialize:initialize()
        handlers.update({task:worker for task in tasks})
    add(identifier_tasks,NativeRegistryWorkers(store,allocate_identifier))
    add(TASK_KINDS,NativeDedupWorkers(store))
    add(outgoing_tasks,NativeOutgoingWorkers(store,websub))
    add(incoming_tasks,NativeIngestionWorkers(store,jsonld_loader=jsonld_loader))
    add(pipeline_tasks,NativePipelineWorkers(store,principal_provider))
    add(['register_export_worker'],NativeExportWorker(store))
    add(['import_file_process_worker'],NativeImportWorker(store,principal_provider,import_sender,import_signature))
    add(['score_compute_worker'],NativeScoreWorker(store))
    add(['intake_form_register_ingest_worker'],NativeIntakeIngestWorker(store))
    return NativeRegistryDispatcher(store.engine,handlers,intervals_from_settings(settings),
        batch_size=int(settings.get('default_batch_size',4)),export_batch_size=int(settings.get('export_batch_size',5)))


class RegistryWorkerRuntime:
    """One scheduler leader per database/schema; handlers retain row-level claims.

    A dedicated autocommit connection owns the session lock. Connection loss
    stops this instance before its next dispatch, allowing another to take over.
    A stop-file is checked between ticks; in-progress atomic handlers finish.
    """
    def __init__(self, dispatcher, heartbeat, stop_file, poll_seconds=1):
        if not .1<=poll_seconds<=60:raise ValueError('Invalid polling interval')
        self.dispatcher=dispatcher
        self.heartbeat,self.stop_file=Path(heartbeat),Path(stop_file)
        self.poll_seconds=poll_seconds
        self.stop=threading.Event()

    def write_health(self,state,**counts):
        payload={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'state':state,
                 'task_count':len(TASKS),**counts}
        self.heartbeat.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        temporary=self.heartbeat.with_name(self.heartbeat.name+'.'+str(os.getpid())+'.tmp')
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as output:json.dump(payload,output)
        os.replace(temporary,self.heartbeat)

    def serve(self, *, max_ticks=None):
        if max_ticks is not None and max_ticks<1:raise ValueError('Positive tick count required')
        with self.dispatcher.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as leader:
            schema=leader.execute(text('SELECT current_schema()')).scalar_one()
            key='native-registry-runtime:'+schema
            locked=leader.execute(text('SELECT pg_try_advisory_lock(hashtextextended(:key,0))'),{'key':key}).scalar_one()
            if not locked:return {'state':'STANDBY','ticks':0}
            ticks=0
            try:
                self.write_health('STARTING')
                while not self.stop.is_set() and not self.stop_file.exists():
                    leader.execute(text('SELECT 1'))
                    outcomes=self.dispatcher.tick()
                    ticks+=1
                    failed=sum(item.get('unexpected_failure',False) or item.get('status') in {'FAILED','RETRY'} for item in outcomes)
                    self.write_health('DEGRADED' if failed else 'RUNNING',dispatched=len(outcomes),failed=failed)
                    if max_ticks is not None and ticks>=max_ticks:break
                    self.stop.wait(self.poll_seconds)
                self.write_health('STOPPED')
                return {'state':'STOPPED','ticks':ticks}
            except Exception:
                self.write_health('FAILED')
                raise
            finally:
                # Never reconnect just to unlock: a replacement connection could
                # own a different session, and disconnect already releases locks.
                if not leader.invalidated:
                    leader.execute(text('SELECT pg_advisory_unlock(hashtextextended(:key,0))'),{'key':key})
