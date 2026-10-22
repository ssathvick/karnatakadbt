"""Ownership-gated native bridge scheduler and durable worker runtime."""
import asyncio,json,logging,os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI,HTTPException
from sqlalchemy import create_engine,text
from starlette.concurrency import run_in_threadpool
from native_bridge_workers import NativeBridgeWorkers
from native_bridge_adapters import NativeBridgeAdapters
from native_domain_ownership import NativeDomainOwnership
from registry_native_write_capture import bind_engine
logging.getLogger('mt940').setLevel(logging.CRITICAL)
logging.getLogger('httpx').setLevel(logging.WARNING)


def build(settings):
    engine=create_engine(settings['database_url'],hide_parameters=True,pool_pre_ping=True)
    mapping=create_engine(settings['mapping_database_url'],hide_parameters=True,pool_pre_ping=True);registry=create_engine(settings['registry_database_url'],hide_parameters=True,pool_pre_ping=True)
    if settings.get('capture_key'):bind_engine(engine,settings['capture_key'],'native-worker')
    enabled=settings.get('processing_enabled') is True;suppressed=settings['suppress_notifications']
    if enabled and (not settings.get('capture_key') or not suppressed and (not settings.get('notification_origin') or not settings.get('notification_token'))):raise ValueError('Explicit capture and delivery capabilities required before worker activation')
    adapters=NativeBridgeAdapters(engine,mapping,registry,bank_origin=settings['bank_origin'],registry_targets=settings['registry_targets'],notification_origin=settings.get('notification_origin'),notification_token=settings.get('notification_token'))
    worker=NativeBridgeWorkers(engine,adapters,max_attempts=settings['max_attempts'],process_future=settings['process_future_disbursement_schedules'],suppress_notifications=suppressed);ownership=NativeDomainOwnership(engine,'bridge');state={'worker_state':'BLOCKED','completed_jobs':0}
    def cycle():
        with ownership.writer():
            for task in worker.SPECS:worker.schedule(task,limit=settings['batch_size'])
            processed=worker.run_one();state['worker_state']='RUNNING';state['completed_jobs']+=int(processed)
            return processed
    async def loop():
        while True:
            try:processed=await run_in_threadpool(cycle);await asyncio.sleep(.1 if processed else 2)
            except asyncio.CancelledError:raise
            except HTTPException:state['worker_state']='BLOCKED';await asyncio.sleep(2)
            except Exception:state['worker_state']='RETRY_REQUIRED';await asyncio.sleep(5)
    @asynccontextmanager
    async def lifespan(app):
        task=asyncio.create_task(loop()) if enabled else None
        try:yield
        finally:
            if task:
                task.cancel()
                try:await task
                except asyncio.CancelledError:pass
            engine.dispose();mapping.dispose();registry.dispose()
    app=FastAPI(title='KarnatakaDBT Native Bridge Workers',lifespan=lifespan)
    @app.get('/health')
    def health():
        with engine.connect() as c:
            owner=c.scalar(text('SELECT owner FROM kdbt_bridge_control.ownership WHERE singleton'));readonly=c.scalar(text('SHOW transaction_read_only'))=='on';pending=c.scalar(text("SELECT count(*) FROM kdbt_bridge_queue.jobs WHERE state='PENDING'"))
        with mapping.connect() as c:mapping_readonly=c.scalar(text('SHOW transaction_read_only'))=='on';c.execute(text('SELECT 1 FROM public.strategy LIMIT 1'))
        with registry.connect() as c:registry_readonly=c.scalar(text('SHOW transaction_read_only'))=='on';c.execute(text('SELECT 1 FROM public.console_record_snapshots LIMIT 1'))
        return {'ready':True,'owner':owner,'database_read_only':readonly,'processing_enabled':enabled,'worker_state':state['worker_state'],'completed_jobs':state['completed_jobs'],'pending_jobs':pending,'business_handlers':11,'schedulers':11,'notifications_suppressed':suppressed,'mapping_dependency_read_only':mapping_readonly,'registry_dependency_read_only':registry_readonly,'legacy_runtime_dependency':False}
    return app


if os.environ.get('KDBT_NATIVE_BRIDGE_WORKER_SETTINGS'):app=build(json.loads(Path(os.environ['KDBT_NATIVE_BRIDGE_WORKER_SETTINGS']).read_text()))
