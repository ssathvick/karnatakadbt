"""Protocol-compatible HTTP surface for the independent bank simulator."""
import json
from pathlib import Path
from fastapi import FastAPI,Form,HTTPException,Request
from fastapi.responses import PlainTextResponse
from native_contract_models import ContractModels


def create_native_bank_app(store,*,writer_admission=None):
    contract=json.loads(Path(__file__).with_name('native_bridge_example_bank_contract.json').read_text());models=ContractModels(contract)
    app=FastAPI(title='KarnatakaDBT Bank Simulator',version='1.0.0')
    @app.middleware('http')
    async def identity(request,call_next):
        response=await call_next(request);response.headers['X-KarnatakaDBT-Bank-Backend']='native';return response
    @app.get('/ping')
    def ping():return 'pong'
    def route(path,method,writable):
        operation=contract['paths'][path]['post'];request_model=models.type(operation['requestBody']['content']['application/json']['schema']);response_model=models.type(operation['responses']['200']['content']['application/json']['schema'])
        def execute(payload,request:Request):
            # initiate_payment has a root array rather than an object DTO.
            body=[item.model_dump(mode='json') for item in payload] if isinstance(payload,list) else payload.model_dump(mode='json')
            if not writable:return getattr(store,method)(body)
            if writer_admission is None:raise HTTPException(503,'Native bank writer remains in standby')
            with writer_admission():
                try:
                    if method in {'block_funds','initiate_payment'}:return getattr(store,method)(body,idempotency_key=request.headers.get('idempotency-key'))
                    return getattr(store,method)(body)
                except ValueError:raise HTTPException(409,'Bank request identity conflicts with retained receipt') from None
        execute.__name__=method;execute.__annotations__['payload']=request_model
        app.add_api_route(path,execute,methods=['POST'],response_model=response_model)
    for path,method,writable in [('/check_funds','check_funds',False),('/block_funds','block_funds',True),('/initiate_payment','initiate_payment',True),('/generate_account_statement','generate_account_statement',True)]:route(path,method,writable)
    @app.post('/ussd',response_class=PlainTextResponse,response_model=str)
    def ussd(sessionId:str=Form(),serviceCode:str=Form(),phoneNumber:str=Form(),networkCode:str=Form(),text:str|None=Form('')):
        return store.ussd(phoneNumber,text)
    return app
