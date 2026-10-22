"""Five compatible ID operations, implemented by the custom Core ledger."""
import contextlib,datetime,json,logging,threading
from pathlib import Path
from typing import Annotated
from fastapi import FastAPI,Path as Parameter
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine,text
from identifier_store import IdentifierStore,valid

FILTER_KEYS=['sequence_limit','repeating_limit','repeating_block_limit','conjugative_even_digits_limit','digits_group_limit','reverse_digits_group_limit','not_start_with','restricted_numbers']

def create_app(engine,config,worker=True):
    store=IdentifierStore(engine);settings=config['id_generator'];types=settings['id_types']
    rules={key:settings[key] for key in FILTER_KEYS};stop=threading.Event()
    def maintain():
        while not stop.is_set():
            try:
                for name in types:
                    if stop.is_set():break
                    if store.ready_count(name)<settings.get('pool_min_threshold',1000):
                        store.replenish(name,target=settings.get('pool_generation_batch_size',5000),budget=.25)
            except Exception:logging.getLogger(__name__).warning('Identifier pool maintenance will retry; connection details withheld.')
            stop.wait(settings.get('pool_check_interval_seconds',30))
    @contextlib.asynccontextmanager
    async def lifespan(app):
        thread=threading.Thread(target=maintain,name='identifier-pools',daemon=True) if worker else None
        if thread:thread.start()
        yield
        stop.set()
        if thread:thread.join(timeout=5)
    app=FastAPI(title='KarnatakaDBT numeric identifier API',version='1.0.0',lifespan=lifespan)
    app.state.store=store
    def envelope(payload=None,code=None,message=None,status=200):
        # Preserve the wire protocol's service identifier for existing clients.
        # This constant is not a dependency on the former implementation.
        return JSONResponse({'id':'openg2p.idgenerator','version':'1.0',
            'responsetime':datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'),
            'response':payload,'errors':[{'errorCode':code,'message':message}] if code else []},status_code=status,
            headers={'X-KarnatakaDBT-Service':'custom-identifiers'})
    def unknown(name):return envelope(code='IDG-003',message=f"Unknown ID type '{name}'",status=404)
    Name=Annotated[str,Parameter(pattern=r'^[a-z][a-z0-9_]{1,63}$')]
    Digits=Annotated[str,Parameter(pattern=r'^\d{1,32}$')]
    @app.post('/v1/idgenerator/{id_type}/id')
    def issue(id_type:Name):
        if id_type not in types:return unknown(id_type)
        try:value,error=store.issue(id_type)
        except Exception:return envelope(code='IDG-006',message='Identifier storage is temporarily unavailable',status=503)
        if error=='exhausted':return envelope(code='IDG-002',message=f"ID space exhausted for ID type '{id_type}'",status=410)
        if error:return envelope(code='IDG-001',message=f"No IDs available for ID type '{id_type}'. Replenishment in progress.",status=503)
        return envelope({'id':value})
    @app.get('/v1/idgenerator/{id_type}/id/validate/{id_value}')
    def validate(id_type:Name,id_value:Digits):
        if id_type not in types:return unknown(id_type)
        return envelope({'id':id_value,'valid':valid(id_value,types[id_type]['id_length'],rules)})
    @app.get('/v1/idgenerator/health')
    def health():
        try:
            with engine.connect() as c:c.execute(text('SELECT 1'));store.ready_count(next(iter(types)))
        except Exception:return envelope(code='IDG-006',message='Identifier storage is temporarily unavailable',status=503)
        return envelope({'status':'UP'})
    @app.get('/v1/idgenerator/version')
    def version():return envelope({'service_version':'1.0.0','build_time':'2026-10-17','git_commit':'custom-core'})
    @app.get('/v1/idgenerator/config')
    def configuration():return envelope({'id_types':types,'filter_rules':rules})
    return app

def native_app():
    root=Path('/runtime/registration')
    engine=create_engine(json.loads((root/'core-connections.json').read_text())['url'],pool_pre_ping=True,hide_parameters=True)
    config=json.loads((root/'identifier-config.json').read_text())
    return create_app(engine,config)
