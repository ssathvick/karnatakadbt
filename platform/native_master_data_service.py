"""Native master-data standby using existing general-purpose PostgreSQL data."""
import json,os
from pathlib import Path
from sqlalchemy import create_engine,text
from native_master_data import NativeMasterData
from native_master_data_api import create_app
from registry_console_auth import RegistryConsoleAuthorizer
from registry_console_ui import mount_registry_console
from native_master_data_ownership import configure_master_writer
from native_administration_admission import AdministrationWriterAdmission

def build(settings):
    writable=settings.get('business_writes_enabled')
    if type(writable) is not bool:raise ValueError('Explicit master-data writer mode required')
    engine=create_engine(settings['database_url'],hide_parameters=True,pool_pre_ping=True)
    ownership=configure_master_writer(engine,settings)
    origins=['https://localhost:8447','https://localhost:8446','https://localhost:8446','https://localhost:8443']
    authority=RegistryConsoleAuthorizer(settings['native_iam_url'],client_id='master-data-ui',allowed_origins=origins,policy_paths={'/geo/get_geo_level_values','/attributes/get_attribute_values'},policy_targets={'GEO','ATTRIBUTE','REGISTER_RECORD'})
    machine_authority=RegistryConsoleAuthorizer(settings['native_iam_url'],client_id='master-data-ui',allowed_origins=(),csrf_enabled=False,policy_paths={'/geo/get_geo_level_values','/attributes/get_attribute_values'},policy_targets={'GEO','ATTRIBUTE','REGISTER_RECORD'})
    async def authorize(request):
        # Existing registry workers use a stateless OAuth bearer. Only reads
        # without browser cookies/origin use this path; IAM still validates it.
        if request.url.path.rsplit('/',1)[-1].startswith('get_') and request.headers.get('authorization','').lower().startswith('bearer ') and not request.cookies and 'origin' not in request.headers:
            return await machine_authority(request)
        return await authority(request)
    app=create_app(NativeMasterData(engine),authorize,standby=not writable)
    mount_registry_console(app,settings['native_iam_url'],origins,'https://localhost:8447/console/',profile='master-data',authorize=authority)
    @app.get('/health')
    def health():
        with engine.connect() as c:readonly=c.execute(text('SHOW transaction_read_only')).scalar_one()=='on'
        if readonly==writable:raise RuntimeError('Master-data credentials differ from configured writer mode')
        admitted=False
        if ownership:
            try:
                with ownership.admission('NATIVE'):admitted=True
            except ValueError:pass
        return {'ready':True,'state':('NATIVE' if admitted else 'AWAITING_OWNERSHIP') if writable else 'STANDBY','database_read_only':readonly,'business_writes_enabled':bool(writable and admitted),'business_operations':16,'legacy_business_http_dependency':False,'existing_postgresql_data_retained':True,'rollback_strategy':'retain_committed_rows_in_shared_database'}
    if ownership:app.add_middleware(AdministrationWriterAdmission,ownership=ownership)
    return app
if os.environ.get('KDBT_NATIVE_MASTER_SETTINGS'):app=build(json.loads(Path(os.environ['KDBT_NATIVE_MASTER_SETTINGS']).read_text()))
