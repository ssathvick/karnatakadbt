"""Deployment binding of the retained consent callback secret to its native store."""
import asyncio,json,os
from pathlib import Path
from native_administration_service import app
settings=json.loads(Path(os.environ['KDBT_NATIVE_ADMIN_SETTINGS']).read_text())
if settings['profile']!='consent-staff':raise ValueError('Explicit consent staff deployment required')
path=Path(settings['callback_settings_path'])
if (os.environ.get('KDBT_DEPLOYMENT_MODE')!='local' and path!=Path('/opt/karnatakadbt/private/g2p-migration/consent-callback/settings.json')) or path.stat().st_mode&0o077:raise ValueError('Private production consent callback binding required')
config=json.loads(path.read_text());secret=config['callback_secret']
if not isinstance(secret,str) or len(secret)<40:raise ValueError('Retained consent callback secret required')
app.state.native_consent_policy.callback_secret=secret
from starlette.concurrency import run_in_threadpool
from native_consent_expiry_worker import NativeConsentExpiryWorker
worker=NativeConsentExpiryWorker(app.state.native_consent_policy.engine)
state={'enabled':settings['business_writes_enabled'],'state':'BLOCKED','expired':0};task=None
async def expire_loop():
    while True:
        try:
            count=await run_in_threadpool(worker.cycle);state.update(state='RUNNING',expired=state['expired']+count)
            await asyncio.sleep(.1 if count==500 else 60)
        except asyncio.CancelledError:raise
        except ValueError:state['state']='BLOCKED';await asyncio.sleep(2)
        except Exception:state['state']='RETRY_REQUIRED';await asyncio.sleep(5)
@app.on_event('startup')
async def start_expiry():
    global task
    if state['enabled']:task=asyncio.create_task(expire_loop())
@app.on_event('shutdown')
async def stop_expiry():
    if task:
        task.cancel()
        try:await task
        except asyncio.CancelledError:pass
@app.get('/expiry-worker/health')
def expiry_health():return {'ready':True,**state}
