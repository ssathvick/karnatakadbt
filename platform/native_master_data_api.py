"""Own master-data HTTP contract, permission and data-policy enforcement."""
import inspect,json
from pathlib import Path
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from registry_contract_models import ContractModels
from registry_metadata_api import RegistryPrincipal,RegistryAuthError,response
from native_master_data import MasterDataError

def create_app(store,authorize,*,standby=False):
    contract=json.loads(Path(__file__).with_name('master_data_contract.json').read_text());permissions=json.loads(Path(__file__).with_name('master_data_console_permissions.json').read_text());models=ContractModels(contract)
    app=FastAPI(title='KarnatakaDBT geography and reference data',version='1.0.0')
    @app.middleware('http')
    async def admission(request,call_next):
        if request.url.path in permissions:
            try:
                principal=authorize(request)
                if inspect.isawaitable(principal):principal=await principal
                if not isinstance(principal,RegistryPrincipal) or not principal.subject:raise RegistryAuthError(401,'Authentication required')
                if not set(permissions[request.url.path]['required_permissions'])<=principal.permissions:raise RegistryAuthError(403,'Assigned master-data permission required')
                if standby and not request.url.path.rsplit('/',1)[-1].startswith('get_'):raise RegistryAuthError(503,'Native master-data writer ownership has not transferred')
                request.state.registry_principal=principal
            except RegistryAuthError as error:return JSONResponse(response('',code='HTTP-'+str(error.status),message=error.message),status_code=error.status,headers={'cache-control':'no-store'})
        result=await call_next(request);result.headers['cache-control']='no-store';result.headers['X-KarnatakaDBT-Native-Profile']='master-data'
        for cookie in getattr(request.state,'registry_auth_cookies',[]):result.headers.append('set-cookie',cookie)
        return result
    def endpoint(path):
        model=models.request_for(path);output=models.response_for(path)
        def handle(data,request:Request):
            body=data.model_dump(mode='json',exclude_unset=True);identifier=body['request_header']['request_id'];request_body=body.get('request_body') or {}
            try:
                payload,pagination=store.execute(path,request_body.get('request_payload') or {},policies=request.state.registry_principal.data_policies,pagination=request_body.get('pagination_request'))
                result=response(identifier,payload);result['response_body']['pagination_response']=pagination
                return output.model_validate(result).model_dump(mode='json')
            except MasterDataError as error:
                result=response(identifier,code=error.code,message=error.message)
                result['response_body']={'pagination_response':None,'response_payload':[] if path.startswith('/geo/get_') else None}
                return JSONResponse(result)
            except ValueError:return JSONResponse(response(identifier,code='HTTP-503',message='Data policy could not be safely evaluated'),status_code=503)
        handle.__annotations__['data']=model
        return handle
    for path in permissions:app.add_api_route(path,endpoint(path),methods=['POST'],response_model=models.response_for(path))
    @app.get('/ping')
    def ping():return {'status':'ok'}
    return app
