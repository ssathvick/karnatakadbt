"""Native audit HTTP contract, with durable admission before 202 responses."""
from datetime import datetime,timezone
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from native_audit_models import AuditEvent,AuditBatch,AuditErrorResponse,AuditAcceptedResponse,AuditBatchAcceptedResponse,AuditHealthResponse,AuditVersionResponse,AuditConfigResponse
from native_audit_store import AuditQueueFull

PREFIX='/v1/auditmanager'
OPERATIONS={('POST',PREFIX+'/events'),('POST',PREFIX+'/events/batch'),('GET',PREFIX+'/health'),('GET',PREFIX+'/version'),('GET',PREFIX+'/config')}

def create_native_audit_api(store,settings,*,ready=lambda:True,lifespan=None):
    app=FastAPI(title='Karnataka DBT native audit',lifespan=lifespan,docs_url=PREFIX+'/docs',redoc_url=PREFIX+'/redoc',openapi_url=PREFIX+'/openapi.json')
    config=settings['audit_manager'];service=config.get('service_id','karnatakadbt.auditmanager')
    def envelope(payload=None,errors=None):
        return {'id':service,'version':config.get('api_version','1.0'),'responsetime':datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'),'response':payload,'errors':errors or []}
    def failure(status,code,message):return JSONResponse(envelope(errors=[{'errorCode':code,'message':message}]),status_code=status)
    @app.middleware('http')
    async def provenance(request,call_next):
        response=await call_next(request);response.headers['X-KarnatakaDBT-Audit-Backend']='native';return response
    @app.exception_handler(RequestValidationError)
    async def invalid(request,error):return failure(422,'AUD-001','Invalid audit event')
    def admission(events,batch=False):
        if not ready() or not settings.get('ingest_enabled',False):return failure(503,'AUD-005','Service not ready')
        limit=config['ingest']['max_batch_size']
        if batch and len(events)>limit:return failure(400,'AUD-007',f'Batch size {len(events)} exceeds limit {limit}')
        try:accepted=store.admit(events)
        except AuditQueueFull as error:
            message=f'Queue full after accepting {len(error.accepted)}/{len(events)}' if batch else 'Audit ingest queue full — backpressure'
            return failure(503,'AUD-004',message)
        except Exception:return failure(503,'AUD-006','Database admission unavailable')
        return JSONResponse(envelope({'accepted':accepted,'count':len(accepted)} if batch else {'accepted':accepted[0]}),status_code=202)
    @app.post(PREFIX+'/events',status_code=202,response_model=AuditAcceptedResponse,responses={422:{'model':AuditErrorResponse},503:{'model':AuditErrorResponse}})
    def ingest(event:AuditEvent):return admission([event])
    @app.post(PREFIX+'/events/batch',status_code=202,response_model=AuditBatchAcceptedResponse,responses={400:{'model':AuditErrorResponse},422:{'model':AuditErrorResponse},503:{'model':AuditErrorResponse}})
    def ingest_batch(batch:AuditBatch):return admission(batch.events,True)
    @app.get(PREFIX+'/health',response_model=AuditHealthResponse,responses={503:{'model':AuditErrorResponse}})
    def health():
        if not ready():return failure(503,'AUD-005','Service not ready: startup not complete')
        try:store.healthy()
        except Exception:return failure(503,'AUD-006','Database health check failed')
        return envelope({'status':'UP'})
    @app.get(PREFIX+'/version',response_model=AuditVersionResponse)
    def version():return envelope({'service_version':'1.0.0-native','build_time':settings.get('build_time','local'),'git_commit':settings.get('source_digest','local')})
    @app.get(PREFIX+'/config',response_model=AuditConfigResponse)
    def configuration():return envelope({'service_id':service,'api_version':config.get('api_version','1.0'),'ingest':config['ingest'],'kafka':{key:config['kafka'][key] for key in ['topic','dlq_topic','consumer_group']},'database':config['database']})
    return app
