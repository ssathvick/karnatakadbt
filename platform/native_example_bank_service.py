"""Native simulator API/worker assembly with explicit production admission."""
import asyncio,json,os,random
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from fastapi import FastAPI,HTTPException
from sqlalchemy import create_engine,text
from starlette.concurrency import run_in_threadpool
from native_example_bank import NativeExampleBank
from native_example_bank_api import create_native_bank_app
from native_example_bank_worker import NativeExampleBankWorker
from native_domain_ownership import NativeDomainOwnership
from registry_native_write_capture import bind_engine
from native_statement_auth import NativeStatementAuthentication


def build(settings):
    if settings['profile'] not in {'api','worker'}:raise ValueError('Explicit simulator service profile required')
    engine=create_engine(settings['database_url'],hide_parameters=True,pool_pre_ping=True)
    if settings.get('capture_key'):bind_engine(engine,settings['capture_key'],'native-api' if settings['profile']=='api' else 'native-worker')
    store=NativeExampleBank(engine);ownership=NativeDomainOwnership(engine,'bank');state={'processing':'BLOCKED','completed_jobs':0}
    callback=settings.get('statement_callback_url')
    callback_auth=NativeStatementAuthentication(settings['statement_callback_keys']) if settings.get('statement_callback_keys') else None
    callback_key=settings.get('statement_callback_key_id')
    def deliver(identifier,body):
        parsed=urlsplit(callback or '')
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:raise ValueError('Explicit statement callback URL required')
        with httpx.Client(trust_env=False,follow_redirects=False,timeout=15) as client:
            headers={'Idempotency-Key':'kdbt-bank-statement-'+str(identifier)}
            if callback_auth:headers.update(callback_auth.headers(callback_key,body.encode()))
            result=client.post(callback,files={'statement_file':('statement.mt940',body,'text/plain')},headers=headers)
            result.raise_for_status()
            return result.json().get('response_header',{}).get('response_status')=='SUCCESS'
    failures=['ACCOUNT_CLOSED','ACCOUNT_NOT_FOUND','ACCOUNT_DORMANT','ACCOUNT_DECEASED'];percent=settings.get('simulated_external_failure_percent',0)
    if not isinstance(percent,int) or not 0<=percent<=100:raise ValueError('Explicit simulator failure percentage required')
    rng=random.SystemRandom()
    worker=NativeExampleBankWorker(store,statement_delivery=deliver if callback else None,payment_attempts=settings.get('payment_attempts',3),simulate_failure=lambda payment:rng.choice(failures) if payment['beneficiary_bank_code']!='EXAMPLE_BANK' and rng.randint(1,100)<=percent else None)
    enabled=settings.get('processing_enabled') is True
    if enabled and (not settings.get('capture_key') or not callback or callback_auth is None or callback_key not in callback_auth.keys):raise ValueError('Durable capture and authenticated statement callback required before worker activation')
    def cycle():
        with ownership.writer():
            worker.batching_request_beat_producer();worker.process_payments_beat_producer();processed=worker.run_one()
            state['processing']='RUNNING';state['completed_jobs']+=int(processed)
            return processed
    async def loop():
        while True:
            try:
                processed=await run_in_threadpool(cycle);await asyncio.sleep(.1 if processed else 2)
            except asyncio.CancelledError:raise
            except HTTPException:
                state['processing']='BLOCKED';await asyncio.sleep(2)
            except Exception:
                state['processing']='RETRY_REQUIRED';await asyncio.sleep(5)
    @asynccontextmanager
    async def lifespan(app):
        task=asyncio.create_task(loop()) if enabled else None
        try:yield
        finally:
            if task:
                task.cancel()
                try:await task
                except asyncio.CancelledError:pass
            engine.dispose()
    app=create_native_bank_app(store,writer_admission=ownership.writer) if settings['profile']=='api' else FastAPI(title='KarnatakaDBT Native Bank Worker',lifespan=lifespan)
    @app.get('/health',include_in_schema=False)
    def health():
        with engine.connect() as c:
            owner=c.execute(text('SELECT owner FROM kdbt_bank_control.ownership WHERE singleton')).scalar_one();readonly=c.execute(text('SHOW transaction_read_only')).scalar_one()=='on'
        return {'ready':True,'profile':settings['profile'],'owner':owner,'database_read_only':readonly,'business_writes_enabled':owner=='NATIVE' and not readonly,'processing_enabled':enabled,'worker_state':state['processing'],'completed_jobs':state['completed_jobs'],'statement_delivery_configured':bool(callback),'legacy_framework_imports':False}
    return app

if os.environ.get('KDBT_NATIVE_BANK_SETTINGS'):
    app=build(json.loads(Path(os.environ['KDBT_NATIVE_BANK_SETTINGS']).read_text()))
