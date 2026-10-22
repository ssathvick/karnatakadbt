"""Private native IAM recovery worker with independent service credentials."""
import asyncio,json,os,time
from contextlib import asynccontextmanager
from pathlib import Path
import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine,text
from starlette.concurrency import run_in_threadpool
from native_identity_admin import NativeIdentityAdmin
from native_identity_recovery_worker import IdentityRecoveryWorker

def build(settings):
    engine=create_engine(settings['database_url'],hide_parameters=True,pool_pre_ping=True)
    key_path=Path(settings['recovery_settings_path'])
    if key_path.stat().st_mode&0o077:raise ValueError('Private recovery settings required')
    key=json.loads(key_path.read_text())['identity_recovery_key'];identity=settings['identity'];cache={}
    def admin():
        if cache.get('expires',0)<=time.monotonic():
            with httpx.Client(trust_env=False,timeout=15) as client:
                result=client.post(identity['origin'].rstrip('/')+'/realms/staff/protocol/openid-connect/token',data={'grant_type':'client_credentials','client_id':identity['client_id'],'client_secret':identity['client_secret']})
                result.raise_for_status();token=result.json()
            cache.update(token=token['access_token'],expires=time.monotonic()+max(1,int(token['expires_in'])-30))
        return NativeIdentityAdmin(identity['origin'],cache['token'])
    worker=IdentityRecoveryWorker(engine,key,admin,allowed_prefix=settings.get('allowed_prefix'));state={'state':'STARTING'}
    async def loop():
        while True:
            try:state.update(await run_in_threadpool(worker.cycle))
            except asyncio.CancelledError:raise
            except Exception:state.update(state='RETRY_REQUIRED')
            await asyncio.sleep(2)
    @asynccontextmanager
    async def lifespan(app):
        task=asyncio.create_task(loop())
        try:yield
        finally:
            task.cancel()
            try:await task
            except asyncio.CancelledError:pass
            engine.dispose()
    app=FastAPI(title='KarnatakaDBT identity recovery worker',lifespan=lifespan)
    @app.get('/health')
    def health():
        with engine.connect() as c:
            owner=c.execute(text("SELECT owner FROM kdbt_administration_control.ownership WHERE profile='iam'")).scalar_one()
            pending=c.execute(text("SELECT count(*) FROM kdbt_iam_identity_effects.intents WHERE state='PENDING'")).scalar_one()
        return {'ready':state['state'] in {'RUNNING','BLOCKED'},'owner':owner,'worker_state':state['state'],'pending_effects':pending,'public_business_writes_allowed':False,'recovery_requires_native_ownership':True,'legacy_business_http_dependency':False}
    return app

if os.environ.get('KDBT_IDENTITY_RECOVERY_WORKER_SETTINGS'):app=build(json.loads(Path(os.environ['KDBT_IDENTITY_RECOVERY_WORKER_SETTINGS']).read_text()))
