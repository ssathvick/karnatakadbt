"""Native IAM console business REST candidate; original login/session retained.

Implements 23 permissioned POST operations and the public safe provider catalogue.
Login/callback/logout sessions and installation self-registration remain separate
migration dependencies; no forwarding of business operations to legacy IAM.
"""
import copy,json,math
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from administration_console_gateway import AdministrationAuthority
from registry_console_ui import mount_registry_console
from registry_metadata_api import RegistryAuthError
from native_contract_models import ContractModels
from native_iam_policy import NativeIamPolicy
from native_iam_business import IamBusinessError
def create_native_iam_api(engine,iam_url,*,identity_factory=None,identity_transport=None,authority=None):
    folder=Path(__file__).parent;contract=json.loads((folder/'iam_console_contract.json').read_text());permissions=json.loads((folder/'iam_console_permissions.json').read_text());models=ContractModels(contract)
    origin='https://localhost:8445';authority=authority or AdministrationAuthority('iam',iam_url,[origin],transport=identity_transport);store=NativeIamPolicy(engine);app=FastAPI(title='KarnatakaDBT native IAM console business API')
    @app.exception_handler(SQLAlchemyError)
    async def persistence_error(request,error):return JSONResponse({'error':'IAM persistence unavailable'},status_code=503,headers={'cache-control':'no-store'})
    mount_registry_console(app,iam_url,[origin],origin+'/console/',profile='iam',authorize=authority,identity_transport=identity_transport)
    @app.get('/auth/get_login_providers')
    def public_login_options():return JSONResponse(store.login_options(),headers={'cache-control':'no-store','x-content-type-options':'nosniff'})
    def endpoint(path):
        operation=path.rsplit('/',1)[-1];required=set(permissions[path]['required_permissions']);schema=contract['paths'][path]['post']['requestBody']['content']['application/json']['schema'];model=models.type(schema,operation+'Input')
        async def execute(request:Request):
            try:
                principal=await authority(request)
                if not required.issubset(principal.permissions):raise RegistryAuthError(403,'Assigned IAM console permission required')
                body=bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body)>8*1024*1024:return JSONResponse({'error':'IAM request is too large'},status_code=413)
                try:parsed=model.model_validate_json(body).model_dump(mode='json')
                except (ValidationError,ValueError):return JSONResponse({'error':'Invalid IAM request'},status_code=422)
                header=parsed.get('request_header') or {};request_body=parsed.get('request_body') or {};data=request_body.get('request_payload') or {};pagination=request_body.get('pagination_request') or {};page=pagination.get('current_page',1);size=pagination.get('page_size',20);total=None
                scoped=copy.copy(store);scoped.identity_admin=identity_factory(request.state.administration_bearer) if identity_factory else None
                try:
                    if operation=='get_applications':value,total=scoped.page('application',page=page,page_size=size)
                    elif operation=='get_application':value=scoped.get('application',data['id'])
                    elif operation=='create_application':value=scoped.create_application(data)
                    elif operation=='update_application':value=scoped.update_application(data)
                    elif operation=='delete_application':value=scoped.delete_application(data)
                    elif operation in {'get_roles','get_permissions','get_role_permissions'}:value,total=scoped.page({'get_roles':'role','get_permissions':'permission','get_role_permissions':'mapping'}[operation],data,page,size)
                    elif operation in {'create_role','create_permission'}:value=scoped.create_access(operation.removeprefix('create_'),data)
                    elif operation in {'delete_role','delete_permission'}:value=scoped.delete_access(operation.removeprefix('delete_'),data)
                    elif operation=='create_role_permission':value=scoped.create_mapping(data)
                    elif operation=='delete_role_permission':value=scoped.delete_mapping(data)
                    elif operation=='get_login_providers':value,total=scoped.page('provider',page=page,page_size=size)
                    elif operation=='get_login_provider':value=scoped.get('provider',data['id'])
                    elif operation=='create_login_provider':value=scoped.create_provider(data)
                    elif operation=='update_login_provider':value=scoped.update_provider(data)
                    elif operation=='delete_login_provider':value=scoped.delete_provider(data['id'])
                    elif operation=='get_policy':value={'policy':scoped.get_policy(data['policy_id'])}
                    elif operation=='get_all_policies':
                        values,total=scoped.all_policies(**{key:data.get(key) for key in ['application_id','policy_target','register_id']});value={'policies':values}
                    elif operation=='add_policy':value={'policy':scoped.add_policy(data)}
                    elif operation=='remove_policy':value=scoped.remove_policy(data['policy_id'])
                    else:raise IamBusinessError('Unsupported IAM operation')
                    result={'response_header':{'request_id':header.get('request_id',''),'response_status':'SUCCESS','response_error_code':'','response_error_message':'','response_timestamp':datetime.now().isoformat()},'response_body':{'response_payload':value,'pagination_response':{'number_of_items':total,'number_of_pages':math.ceil(total/size) if size>0 else 0} if total is not None else None}}
                except IamBusinessError as error:
                    if path.startswith('/data-policies/'):return JSONResponse({'errors':[{'code':error.code,'message':error.message}]},status_code=400)
                    result={'response_header':{'request_id':header.get('request_id',''),'response_status':'ERROR','response_error_code':error.code,'response_error_message':error.message,'response_timestamp':datetime.now().isoformat()},'response_body':{'response_payload':None,'pagination_response':None}}
                response=JSONResponse(result,headers={'cache-control':'no-store'})
                for value in getattr(request.state,'registry_auth_cookies',[]):response.headers.append('set-cookie',value)
                return response
            except RegistryAuthError as error:return JSONResponse({'error':error.message},status_code=error.status,headers={'cache-control':'no-store'})
        return execute
    for path in permissions:
        if 'post' in contract['paths'][path]:app.add_api_route(path,endpoint(path),methods=['POST'])
    app.state.native_iam_business_operations=sum('post' in contract['paths'][path] for path in permissions);app.state.legacy_authentication_and_permission_lookup_retained=True
    return app
