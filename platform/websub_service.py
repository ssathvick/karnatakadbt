"""Frozen, private configuration for the native internal WebSub service."""
import datetime,json,logging,os
from pathlib import Path
from sqlalchemy import create_engine
from websub_hub import HubStore,create_hub_app
logging.getLogger('httpx').setLevel(logging.WARNING)
configuration=Path(os.environ['KDBT_WEBSUB_SETTINGS'])
settings=json.loads(configuration.read_text())
engine=create_engine(settings['url'],hide_parameters=True,pool_pre_ping=True,pool_size=4,max_overflow=4)
store=HubStore(engine,settings['encryption_key'].encode(),settings['hub_url'],max_attempts=settings.get('max_attempts',5),backoff_seconds=settings.get('backoff_seconds',5));store.initialize()
def heartbeat(state,counts):
    path=configuration.parent/'websub-worker-status.json';temporary=path.with_suffix('.tmp')
    fd=os.open(temporary,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as output:json.dump({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'state':state,**counts},output)
    os.replace(temporary,path)
app=create_hub_app(store,settings['publisher_token'],settings.get('subscription_permits',[]),heartbeat=heartbeat)
