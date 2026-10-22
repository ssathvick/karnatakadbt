"""Standalone native audit service; no legacy Python packages are imported."""
import json,os
from contextlib import asynccontextmanager
from pathlib import Path
from sqlalchemy import create_engine
from native_audit_store import NativeAuditStore
from native_audit_runtime import NativeAuditRuntime
from native_audit_api import create_native_audit_api

def build(settings):
    engine=create_engine(settings['database_url'],hide_parameters=True,pool_pre_ping=True)
    store=NativeAuditStore(engine,queue_max_size=settings['audit_manager']['ingest']['queue_max_size']);runtime=NativeAuditRuntime(store,settings)
    @asynccontextmanager
    async def lifespan(app):
        try:
            await runtime.start();yield
        finally:
            await runtime.stop();engine.dispose()
    return create_native_audit_api(store,settings,ready=lambda:runtime.ready,lifespan=lifespan)

if os.environ.get('KDBT_NATIVE_AUDIT_SETTINGS'):app=build(json.loads(Path(os.environ['KDBT_NATIVE_AUDIT_SETTINGS']).read_text()))
