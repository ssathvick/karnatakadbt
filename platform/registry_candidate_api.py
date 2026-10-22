"""Typed partial registry replacement with console auth and durable HTTP audit.

Only explicitly implemented paths are registered. This is not a proxy for
unimplemented business operations and does not configure production routing.
"""
import inspect,json,logging
from pathlib import Path
from fastapi import FastAPI,Request,UploadFile,File,Form
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from registry_contract_models import ContractModels
from registry_metadata_api import RegistryPrincipal,RegistryAuthError,response
from registry_metadata_store import RegistryError
from registry_data_policy import POLICY_PATHS
from registry_route_auth import AWE_PATHS,required_permissions

def create_app(store,paths,authorize,audit):
    contract=json.loads(Path(__file__).with_name('registry_full_contract.json').read_text())
    paths=frozenset(paths);models=ContractModels(contract)
    app=FastAPI(title='KarnatakaDBT registry replacement candidate',version='0.2.0')
    for path in paths:
        required_permissions(path,contract)

    @app.middleware('http')
    async def protected(request,call_next):
        result=None;business_error=False;key=None
        def decorate(value):
            value.headers['Cache-Control']='no-store';value.headers['X-Content-Type-Options']='nosniff'
            value.headers['X-KarnatakaDBT-Service']='registry-candidate'
            for cookie in getattr(request.state,'registry_auth_cookies',[]):value.headers.append('set-cookie',cookie)
            return value
        if request.url.path not in paths:return decorate(await call_next(request))
        try:
            key=await run_in_threadpool(audit.begin,request.url.path,request.method)
        except Exception:
            return decorate(JSONResponse(response('',code='HTTP-503',message='Audit storage unavailable'),status_code=503))
        try:
            principal=authorize(request) if authorize else None
            if inspect.isawaitable(principal):principal=await principal
            if not isinstance(principal,RegistryPrincipal) or not principal.subject:
                raise RegistryAuthError(401,'Authentication required')
            request.state.registry_principal=principal
            required=required_permissions(request.url.path,contract)
            if not required.issubset(principal.permissions):raise RegistryAuthError(403,'Assigned console permission required')
            result=await call_next(request)
        except RegistryAuthError as error:
            result=JSONResponse(response('',code='HTTP-'+str(error.status),message=error.message),status_code=error.status)
        except Exception:
            result=JSONResponse(response('',code='HTTP-500',message='Request failed'),status_code=500)
        try:
            actor=getattr(request.state,'registry_principal',None)
            await run_in_threadpool(audit.finish,key,actor.subject if actor else None,result.status_code,getattr(request.state,'registry_business_error',False))
        except Exception:
            # The durable admission record remains PENDING for reconciliation.
            # Never turn a committed business write into a retryable 503.
            logging.getLogger(__name__).error('HTTP audit completion pending for event %s',key)
        return decorate(result)

    def endpoint(path):
        if path=='/input-mechanism-data/ingest-data':
            output=models.response_for(path)
            async def ingest_data(request:Request,data_model:str|None=None,register_id:str|None=None,intake_form_id:str|None=None):
                try:
                    body=await request.json();value=await run_in_threadpool(store.admit_ingest,body,dict(request.headers),{'data_model':data_model,'register_id':register_id,'intake_form_id':intake_form_id},request.state.registry_principal)
                    return JSONResponse(output.model_validate(response('',value)).model_dump(mode='json'))
                except RegistryError as error:
                    request.state.registry_business_error=True
                    return JSONResponse(response('',code=error.code,message=error.message))
                except RegistryAuthError as error:
                    request.state.registry_business_error=True
                    return JSONResponse(response('',code='HTTP-'+str(error.status),message=error.message),status_code=error.status)
                except Exception:
                    request.state.registry_business_error=True
                    return JSONResponse(response('',code='SYS-ERR-001',message='UNEXPECTED_ERROR'))
            return ingest_data
        if path=='/documents/upload_documents':
            output=models.response_for(path)
            async def upload_documents(request:Request,documents:list[UploadFile]=File(...,description='List of documents to upload'),bucket=Form('documents',description='Target document bucket')):
                try:
                    files=[(file.filename,await file.read(),file.content_type) for file in documents]
                    value=await run_in_threadpool(store.upload,files,bucket,request.state.registry_principal)
                    return output.model_validate(response('',value)).model_dump(mode='json')
                except RegistryError as error:
                    request.state.registry_business_error=True
                    return JSONResponse(response('',code=error.code,message=error.message))
                except Exception:
                    request.state.registry_business_error=True
                    return JSONResponse(response('',code='SYS-ERR-001',message='UNEXPECTED_ERROR'))
            upload_documents.__annotations__['bucket']=models.model('DocumentBucket')
            return upload_documents
        model=models.request_for(path);output=models.response_for(path)
        def handle(data,request:Request):
            body=data.model_dump(mode='json');request_id=body['request_header']['request_id']
            envelope=body.get('request_body') or {};payload=envelope.get('request_payload') or {}
            if path in {'/verifications/add_verification','/change-requests/add_verification_for_change_request'}:payload['verified_by']=request.state.registry_principal.name or 'Unknown'
            try:
                if path in AWE_PATHS:
                    value,pagination=store.execute_awe_request(path,envelope,request.state.registry_principal)
                elif path in POLICY_PATHS:
                    value,pagination=store.execute_policy_request(path,payload,request.state.registry_principal,envelope.get('pagination_request'))
                elif hasattr(store,'execute_request'):
                    value,pagination=store.execute_request(path,payload,request.state.registry_principal.subject,envelope.get('pagination_request'))
                else:value,pagination=store.execute(path,payload,request.state.registry_principal.subject),None
                result=response(request_id,value)
                result['response_body']['pagination_response']=pagination
                return output.model_validate(result).model_dump(mode='json')
            except RegistryError as error:
                request.state.registry_business_error=True
                return JSONResponse(response(request_id,code=error.code,message=error.message))
            except RegistryAuthError as error:
                request.state.registry_business_error=True
                return JSONResponse(response(request_id,code='HTTP-'+str(error.status),message=error.message),status_code=error.status)
            except Exception:
                request.state.registry_business_error=True
                return JSONResponse(response(request_id,code='SYS-ERR-001',message='UNEXPECTED_ERROR'))
        handle.__annotations__['data']=model
        return handle
    for path in sorted(paths):app.add_api_route(path,endpoint(path),methods=['POST'],name=path.rsplit('/',1)[-1],response_model=models.response_for(path))
    return app
