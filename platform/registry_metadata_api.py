"""13 candidate operations; production traffic stays on the original 204-op API."""
import dataclasses,datetime,inspect,json
from pathlib import Path
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from registry_contract_models import ContractModels
from registry_metadata_store import RegistryError

@dataclasses.dataclass(frozen=True)
class RegistryPrincipal:
    subject:str
    permissions:frozenset[str]
    name:str|None=None
    data_policies:tuple[dict,...]=()
    bearer_token:str|None=dataclasses.field(default=None,repr=False,compare=False)
    policy_mnemonics:tuple[str,...]=()

class RegistryAuthError(Exception):
    def __init__(self,status,message):
        self.status=status;self.message=message;super().__init__(message)

def response(request_id,payload=None,code=None,message=None):
    return {'response_header':{'request_id':request_id,'response_status':'ERROR' if code else 'SUCCESS',
        'response_error_code':code or '','response_error_message':message or '',
        'response_timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat()},
        'response_body':None if code else {'pagination_response':None,'response_payload':payload}}

def create_app(store,authorize=None,contract=None):
    # No native factory is exposed until the console's real authentication,
    # refresh, CSRF and revocation behaviour has passed a separate parity gate.
    contract=contract or json.loads(Path(__file__).with_name('registry_metadata_contract.json').read_text())
    models=ContractModels(contract);app=FastAPI(title='KarnatakaDBT registry metadata candidate',version='0.1.0')
    @app.middleware('http')
    async def authenticate(request,call_next):
        def finish(result):
            result.headers['Cache-Control']='no-store'
            result.headers['X-KarnatakaDBT-Service']='registry-metadata-candidate'
            result.headers['X-Content-Type-Options']='nosniff'
            for cookie in getattr(request.state,'registry_auth_cookies',[]):
                result.headers.append('set-cookie',cookie)
            return result
        if request.url.path in contract['paths']:
            try:
                principal=authorize(request) if authorize else None
                if inspect.isawaitable(principal):principal=await principal
            except RegistryAuthError as error:
                return finish(JSONResponse(response('',code='HTTP-'+str(error.status),message=error.message),status_code=error.status))
            except Exception:principal=None
            if not isinstance(principal,RegistryPrincipal) or not principal.subject:
                return finish(JSONResponse(response('',code='HTTP-401',message='Authentication required'),status_code=401))
            operation=request.url.path.rsplit('/',1)[-1]
            if not operation.startswith('get_') and 'registryConfiguration:edit' not in principal.permissions:
                return finish(JSONResponse(response('',code='HTTP-403',message='Assigned registry configuration permission required'),status_code=403))
            request.state.registry_principal=principal
        return finish(await call_next(request))
    def endpoint(path):
        model=models.request_for(path);output=models.response_for(path)
        def handle(data,request:Request):
            body=data.model_dump(mode='json');request_id=body['request_header']['request_id'];payload=(body.get('request_body') or {}).get('request_payload') or {}
            try:
                result=store.execute(path,payload,request.state.registry_principal.subject)
                return output.model_validate(response(request_id,result)).model_dump(mode='json')
            except RegistryError as error:return JSONResponse(response(request_id,code=error.code,message=error.message))
            except Exception:return JSONResponse(response(request_id,code='SYS-ERR-001',message='UNEXPECTED_ERROR'))
        handle.__annotations__['data']=model
        return handle
    for path in contract['paths']:app.add_api_route(path,endpoint(path),methods=['POST'],name=path.rsplit('/',1)[-1],response_model=models.response_for(path))
    return app
