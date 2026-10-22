"""Deployable native approval API and worker lifecycle; settings stay private."""
import asyncio,datetime,json,os,ssl,threading,time
from pathlib import Path
from urllib.parse import urlsplit
import httpx,jwt
from sqlalchemy import create_engine
from approval_auth import ApprovalTokenVerifier
from approval_integrations import ApprovalDirectory,ApproverResolver
from approval_engine_store import ApprovalEngineStore
from approval_engine_api import create_engine_app
from approval_data_migration import ApprovalDataMigration
from approval_workers import ApprovalWorkers
from cryptography.fernet import Fernet

settings=json.loads(Path(os.environ['KDBT_APPROVAL_SETTINGS']).read_text())
context=ssl.create_default_context(cafile=settings['ca_file'])
issuer=settings['issuer'];jwks=jwt.PyJWKClient(settings['jwks_url'],ssl_context=context)
authenticate=ApprovalTokenVerifier(settings['accepted_issuers'],settings['audience'],settings['jwks_url'],key_lookup=jwks.get_signing_key_from_jwt)
directory_cfg=settings['directory']
directory=ApprovalDirectory(directory_cfg['base_url'],directory_cfg['realm'],directory_cfg['client_id'],directory_cfg['client_secret'],transport=httpx.HTTPTransport(verify=context))
engine=create_engine(settings['url'],hide_parameters=True,connect_args={'options':'-csearch_path='+settings['schema']},pool_pre_ping=True)
store=ApprovalEngineStore(engine,resolver=ApproverResolver(directory,settings.get('resolver_origins',[])))
migration=ApprovalDataMigration(store,Path(settings['archive_key_path']).read_bytes())
app=create_engine_app(store,authenticate,directory,settings['public_config'],settings['callback_origins'])

class ClusterTransport(httpx.BaseTransport):
    def __init__(self):self.inner=httpx.HTTPTransport(verify=context)
    def handle_request(self,request):
        original=request.url;alias=settings.get('cluster_hosts',{}).get(original.host)
        if alias and original.scheme=='http':
            request.headers['host']=original.netloc.decode();request.url=original.copy_with(host=alias)
        try:return self.inner.handle_request(request)
        finally:request.url=original
    def close(self):self.inner.close()

def callback_secret(identifier):
    path=settings.get('native_callback_secrets_path')
    if path:
        values=json.loads(Fernet(Path(settings['archive_key_path']).read_bytes()).decrypt(Path(path).read_bytes()))
        if identifier in values:return values[identifier]
    return migration.secret(identifier)

workers=ApprovalWorkers(store,callback_secret,settings['callback_origins'],transport=ClusterTransport(),
    max_attempts=settings['public_config']['webhook']['max_attempts'],backoff_seconds=settings['public_config']['webhook']['backoff_seconds'],
    timeout=settings['public_config']['webhook']['timeout_seconds'])
stop=threading.Event();thread=None
def worker_loop():
    last_sla=0
    while not stop.is_set():
        try:
            workers.dispatch()
            if time.monotonic()-last_sla>=settings['public_config']['sla']['check_interval_seconds']:
                workers.sla_tick();last_sla=time.monotonic()
            heartbeat=Path(os.environ['KDBT_APPROVAL_SETTINGS']).parent/'service-worker-status.json'
            heartbeat.write_text(json.dumps({'passed':True,'at':datetime.datetime.now(datetime.timezone.utc).isoformat()}));heartbeat.chmod(0o600)
        except Exception:
            # Never log callback bodies, records, credentials or raw SQL.
            print('Native approval worker tick failed; durable work retained',flush=True)
        stop.wait(2)

@app.on_event('startup')
def start_workers():
    global thread
    if settings.get('workers_enabled'):
        thread=threading.Thread(target=worker_loop,name='native-approval-workers',daemon=True);thread.start()

@app.on_event('shutdown')
def stop_workers():
    stop.set()
    if thread:thread.join(timeout=15)
    engine.dispose()
