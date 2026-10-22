"""Native worker service; dispatch remains closed until coordinated ownership."""
import json,os,signal,time
from pathlib import Path
from sqlalchemy import create_engine
from registry_worker_runtime import RegistryWorkerRuntime,IdentifierHttpClient,assemble_workers
from registry_worker_admission import RegistryWorkerAdmission
from registry_worker_authority import WorkerAuthority
from registry_outgoing_workers import NativeWebsub
from registry_approval_store import RegistryApprovalStore
from registry_awe_client import ApprovalEngineClient
from registry_candidate_storage import CandidateS3Storage
from registry_master_codes import MasterCodeClient
from registry_partner_client import RegistryPartnerClient


def configured(settings):
    private=Path(settings['candidate_settings_directory'])
    def read(name):return json.loads((private/name).read_text())
    authority=WorkerAuthority(read('worker-authority-settings.json'))
    websub_settings=read('websub-client-settings.json')
    websub=NativeWebsub(websub_settings['endpoint'],websub_settings['allowed_origins'],publisher_token=websub_settings['publisher_token'])
    identifier=IdentifierHttpClient(settings['identifier_url'],[settings['identifier_url']],{'household':'household','individual':'individual'})
    integration=read('worker-integration-settings.json')
    if not integration.get('import_file_sender_id') or not integration.get('import_file_signature'):raise ValueError('Real import admission configuration required')
    return private,read,authority,websub,identifier,integration


def serve(settings):
    private,read,authority,websub,identifier,integration=configured(settings)
    engine=create_engine(settings['url'],hide_parameters=True,pool_pre_ping=True)
    if settings.get('native_capture_key_path'):
        from registry_native_write_capture import bind_engine
        bind_engine(engine,Path(settings['native_capture_key_path']).read_text().strip(),writer='native-worker')
    admission=RegistryWorkerAdmission(engine,settings['handoff_scope']);runtime=None;stopped=[False]
    def stop(*args):stopped[0]=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    health=RegistryWorkerRuntime(type('StandbyDispatcher',(),{'engine':engine})(),settings['health_file'],settings['stop_file'])
    try:
        while not stopped[0] and not Path(settings['stop_file']).exists():
            try:
                with admission.acquire() as accepted:
                    if not accepted:health.write_health('BLOCKED',ownership_admitted=False,dispatched=0)
                    else:
                        # All handlers, including identifier/completion jobs,
                        # require the dedicated live service identity before a
                        # dispatch tick can begin. Ownership alone is not auth.
                        authority(None,{})
                        # Never initialize handlers or touch queues while the
                        # source-authoritative synchronizer owns these records.
                        if settings.get('sync_health_file'):
                            sync=json.loads(Path(settings['sync_health_file']).read_text())
                            if sync.get('state')!='STOPPED':raise ValueError('Source synchronizer must be stopped before native dispatch')
                        else:
                            from standalone_ownership import identity
                            identity()  # Fresh local profile has no historical source synchronizer.
                        if runtime is None:
                            store=RegistryApprovalStore(engine,CandidateS3Storage(read('storage-settings.json')),awe_client=ApprovalEngineClient(settings['approval_url']),workflow_settings=read('workflow-settings.json'),master_codes=MasterCodeClient(read('master-data-settings.json')),partner_client=RegistryPartnerClient(read('partner-management-candidate-settings.json')),registrant_auth_settings=read('registrant-auth-candidate-settings.json'))
                            store.initialize()
                            dispatcher=assemble_workers(store,principal_provider=authority,allocate_identifier=identifier,websub=websub,import_sender=integration['import_file_sender_id'],import_signature=integration['import_file_signature'],settings=settings['scheduling'])
                            runtime=RegistryWorkerRuntime(dispatcher,settings['health_file'],settings['stop_file'])
                        runtime.serve(max_ticks=1);health.write_health('RUNNING',ownership_admitted=True)
            except Exception:
                # Do not expose SQL, job payloads or private connection strings.
                health.write_health('BLOCKED',ownership_admitted=False,partial_tick_possible=runtime is not None,error_code='NATIVE_WORKER_ADMISSION_OR_RUNTIME_FAILURE')
            for _ in range(10):
                if stopped[0]:break
                time.sleep(.2)
    finally:health.write_health('STOPPED',ownership_admitted=False);engine.dispose()


if __name__=='__main__':serve(json.loads(Path(os.environ['KDBT_REGISTRY_WORKER_SETTINGS']).read_text()))
