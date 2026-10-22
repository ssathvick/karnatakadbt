"""Master-data admission with legacy SQL fenced on the retained shared DB.

Rollback keeps committed native rows in this same database; it never restores
an old snapshot over newer writes. Only the native runtime holds the private
transaction-local SQL fence capability.
"""
import hashlib,json
from pathlib import Path
from contextlib import contextmanager
from sqlalchemy import event,text
from native_administration_ownership import AdministrationOwnership

class MasterDataOwnership(AdministrationOwnership):
    def __init__(self,engine,settings):
        self.engine,self.profile,self.lock=engine,'master-data','karnatakadbt-administration-ownership:master-data'
        self.settings=settings

    @contextmanager
    def admission(self,owner):
        with super().admission(owner):
            if owner=='NATIVE':
                with self.engine.begin() as c:
                    c.execute(text("SELECT pg_advisory_xact_lock_shared(hashtextextended('karnatakadbt:registry-producers:v1',0))"))
                    row=c.execute(text('SELECT fenced,owner,capability_hash FROM kdbt_migration_fence.control WHERE singleton')).one()
                    if not row.fenced or row.owner!=self.settings['fence_owner'] or row.capability_hash!=hashlib.sha256(self.settings['fence_capability'].encode()).hexdigest():
                        raise ValueError('Legacy master-data SQL producers must remain fenced')
                    yield
            else:yield

def configure_master_writer(engine,settings):
    if settings.get('business_writes_enabled') is not True:return None
    if settings.get('writer_ownership_scope')!='master-data':raise ValueError('Explicit master-data ownership required')
    path=Path(settings['master_ownership_settings_path'])
    if path.stat().st_mode&0o077:raise ValueError('Master-data ownership settings must be private')
    config=json.loads(path.read_text())
    if len(config['fence_capability'])<40 or not config['fence_owner']:raise ValueError('Persistent master-data fence capability required')
    with engine.connect() as c:
        row=c.execute(text('SELECT current_database(),(SELECT oid::text FROM pg_database WHERE datname=current_database())')).one()
        source=c.execute(text("SELECT source_id::text FROM kdbt_administration_control.ownership WHERE profile='master-data'")).scalar_one()
    if list(row)!=[config['database_identity']['database'],config['database_identity']['database_oid']] or source!=config['source_id']:
        raise ValueError('Master-data database or ownership identity differs')
    @event.listens_for(engine,'begin')
    def authorize(c):c.exec_driver_sql("SELECT set_config('kdbt_migration.fence_capability',%s,true)",(config['fence_capability'],))
    return MasterDataOwnership(engine,config)
