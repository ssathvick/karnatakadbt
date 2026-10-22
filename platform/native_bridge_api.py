"""Native bridge HTTP boundary; all authentication and writers fail closed."""
import inspect,json
from pathlib import Path
from fastapi import FastAPI,File,HTTPException,Request,UploadFile
from starlette.concurrency import run_in_threadpool
from native_contract_models import ContractModels


def create_native_bridge_app(*,profile,business=None,queries=None,beneficiary=None,statements=None,authorize=None,writer_admission=None,authorize_callback=None):
    if profile not in {'partner','beneficiary'}:raise ValueError('Explicit bridge profile required')
    contract=json.loads(Path(__file__).with_name('native_bridge_'+profile+'_contract.json').read_text());models=ContractModels(contract)
    app=FastAPI(title='KarnatakaDBT Native Bridge '+profile.title(),version='1.0.0')
    @app.get('/ping')
    def ping():return 'pong'
    async def authenticate(request):
        if authorize is None:raise HTTPException(503,'Native bridge authentication integration unavailable')
        value=await authorize(request) if inspect.iscoroutinefunction(authorize) else await run_in_threadpool(authorize,request)
        if not value:raise HTTPException(401,'Verified bridge principal required')
        return value
    def route(path):
        operation=path.rsplit('/',1)[-1];definition=contract['paths'][path]['post'];request_model=models.type(definition['requestBody']['content']['application/json']['schema']);response_model=models.type(definition['responses']['200']['content']['application/json']['schema'])
        async def handle(payload,request:Request):
            principal=await authenticate(request);body=payload.model_dump(mode='json')
            def execute():
                if profile=='beneficiary':
                    if not isinstance(principal,str):raise HTTPException(401,'Verified subject required')
                    return beneficiary.execute(operation,body,subject=principal)
                if operation.startswith('get_'):return queries.execute(operation,body)
                if writer_admission is None:raise HTTPException(503,'Native bridge writer remains in standby')
                with writer_admission():return business.execute(operation,body)
            return await run_in_threadpool(execute)
        handle.__name__=operation;handle.__annotations__['payload']=request_model
        app.add_api_route(path,handle,methods=['POST'],response_model=response_model)
    for path in contract['paths']:
        if path not in {'/ping','/upload_mt940'}:route(path)
    if profile=='partner':
        response_model=models.type(contract['paths']['/upload_mt940']['post']['responses']['200']['content']['application/json']['schema'])
        @app.post('/upload_mt940',response_model=response_model)
        async def upload(request:Request,statement_file:UploadFile=File(...)):
            if statements is None:raise HTTPException(503,'Native statement ingestion unavailable')
            if authorize_callback is None:await authenticate(request)
            body=await statement_file.read(statements.max_size+1)
            if authorize_callback is not None:
                principal=await run_in_threadpool(authorize_callback,request,body)
                if not principal:raise HTTPException(401,'Verified callback service required')
            if writer_admission is None:raise HTTPException(503,'Native statement writer remains in standby')
            def execute():
                with writer_admission():return statements.upload(body,statement_file.content_type)
            return await run_in_threadpool(execute)
    return app
