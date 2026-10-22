"""Native registry HTTP surface with standby and fenced writer admission."""
import json,os
from pathlib import Path
from sqlalchemy import create_engine,text
from fastapi.responses import JSONResponse
from registry_candidate import IMPLEMENTED_PATHS
from registry_candidate_api import create_app
from registry_approval_webhook import RegistryApprovalWebhookStore,WEBHOOK_PATH
from registry_registrant_auth_store import CALLBACK_PATH
from registry_approval_webhook_api import install_approval_webhook
from registry_registrant_callback import install_registrant_callback
from registry_candidate_storage import CandidateS3Storage
from registry_awe_client import ApprovalEngineClient
from registry_master_codes import MasterCodeClient
from registry_partner_client import RegistryPartnerClient
from registry_http_audit import RegistryHttpAudit
from registry_console_auth import RegistryConsoleAuthorizer
from registry_console_ui import mount_registry_console
from registry_health import install_health,HEALTH_PATHS

def build(settings):
    writable=settings.get('business_writes_enabled')
    if type(writable) is not bool:raise ValueError('Explicit registry business writer mode required')
    if writable and (settings.get('writer_ownership_scope')!='registry' or not settings.get('native_capture_key_path')):raise ValueError('Writable registry requires global ownership scope and mandatory capture')
    engine=create_engine(settings['database_url'],hide_parameters=True,pool_pre_ping=True);audit_engine=create_engine(settings['audit_database_url'],hide_parameters=True,pool_pre_ping=True)
    if settings.get('native_capture_key_path'):
        from registry_native_write_capture import bind_engine
        bind_engine(engine,Path(settings['native_capture_key_path']).read_text().strip(),writer='native-api')
    private=Path(settings['candidate_settings_directory'])
    def read(name):return json.loads((private/name).read_text())
    master_settings=read('master-data-settings.json');partner_settings=read('partner-management-candidate-settings.json')
    store=RegistryApprovalWebhookStore(engine,CandidateS3Storage(read('storage-settings.json')),awe_client=ApprovalEngineClient(settings['approval_url']),workflow_settings=read('workflow-settings.json'),master_codes=MasterCodeClient(master_settings),partner_client=RegistryPartnerClient(partner_settings),registrant_auth_settings=read('registrant-auth-candidate-settings.json'),webhook_settings=settings['webhook_settings'])
    origins=['https://localhost:8446','https://localhost:8446','https://localhost:8443'];authority=RegistryConsoleAuthorizer(settings['native_iam_url'],allowed_origins=origins);audit=RegistryHttpAudit(audit_engine)
    app=create_app(store,IMPLEMENTED_PATHS-HEALTH_PATHS-{CALLBACK_PATH,WEBHOOK_PATH},authority,audit);install_health(app);install_registrant_callback(app,store,audit);install_approval_webhook(app,store,audit)
    partner_paths=frozenset()
    if settings.get('partner_runtime_settings_path'):
        from registry_partner_api import install_partner_api,PATHS
        partner_configuration=json.loads(Path(settings['partner_runtime_settings_path']).read_text())
        install_partner_api(app,store,audit,partner_configuration);partner_paths=PATHS
    business_paths=IMPLEMENTED_PATHS|partner_paths
    mount_registry_console(app,settings['native_iam_url'],origins,'https://localhost:8446/console/',authorize=authority)
    safe_reads={path for path in IMPLEMENTED_PATHS if path.rsplit('/',1)[-1].startswith(('get_','list_','search_'))}|{'/awe/my_task_stats'}
    # These paths consume state or contact external identity services, so they
    # remain blocked even though their names include get/authentication.
    safe_reads-={'/register-data/authenticate_registrant',CALLBACK_PATH,WEBHOOK_PATH}
    ownership=None
    if writable:
        from registry_http_ownership import install_registry_http_ownership
        ownership=install_registry_http_ownership(app,engine,business_paths=business_paths,safe_reads=safe_reads,health_paths=HEALTH_PATHS)
    @app.middleware('http')
    async def standby(request,call_next):
        if not writable and request.url.path in business_paths and request.url.path not in safe_reads|HEALTH_PATHS:
            return JSONResponse({'error':'Native registry standby; business ownership has not transferred'},status_code=503,headers={'cache-control':'no-store','retry-after':'5'})
        result=await call_next(request);result.headers['X-KarnatakaDBT-Native-Profile']='registry';return result
    @app.get('/health')
    def health():
        with engine.connect() as c:readonly=c.execute(text('SHOW transaction_read_only')).scalar_one()=='on'
        if readonly==writable:raise RuntimeError('Registry database credentials do not match configured writer mode')
        dependencies=[]
        if master_settings.get('api_url')!='http://127.0.0.1:18121':dependencies.append('master-data')
        if any(partner_settings.get(key)!='http://127.0.0.1:18113' for key in ['admin_api_url','keys_api_url']):dependencies.append('partner-management')
        admitted=False
        if ownership:
            with ownership.acquire() as accepted:admitted=accepted
        return {'ready':True,'database_read_only':readonly,'business_writes_enabled':bool(writable and admitted),'writer_configured':writable,'ownership_admitted':admitted,'registered_registry_paths':len(IMPLEMENTED_PATHS),'native_partner_business_paths':len(partner_paths),'native_iam_used':True,'source_registry_http_dependency':False,'retained_external_dependencies':dependencies,'native_master_data_used':'master-data' not in dependencies,'native_partner_used':'partner-management' not in dependencies,'production_source_synchronization_still_required':not admitted,'state':('NATIVE' if admitted else 'AWAITING_OWNERSHIP') if writable else 'STANDBY'}
    return app

if os.environ.get('KDBT_NATIVE_REGISTRY_SETTINGS'):app=build(json.loads(Path(os.environ['KDBT_NATIVE_REGISTRY_SETTINGS']).read_text()))
