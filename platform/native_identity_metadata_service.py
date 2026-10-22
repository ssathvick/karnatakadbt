"""Public validation metadata for approved identity providers; no secrets."""
import json,os
from pathlib import Path
from fastapi import FastAPI,HTTPException
from fastapi import Request
from fastapi.responses import JSONResponse
import httpx
from sqlalchemy import create_engine,text

def build(settings):
    engine=create_engine(settings['database_url'],hide_parameters=True,pool_pre_ping=True)
    app=FastAPI(title='KarnatakaDBT identity validation metadata')
    @app.get('/health')
    def health():
        with engine.connect() as c:readonly=c.execute(text('SHOW transaction_read_only')).scalar_one()=='on'
        if not readonly:raise HTTPException(503,'Read-only identity metadata connection required')
        return {'ready':True,'database_read_only':True,'private_identity_fields_exposed':False}
    @app.get('/identity-providers/get_provider_by_issuer')
    def provider(issuer:str):
        if not issuer or len(issuer)>2048:raise HTTPException(404,'Provider unavailable')
        with engine.connect() as c:
            # This consumer contract deliberately omits client_secret, private
            # assertions, credentials and every administrative mutation.
            rows=c.execute(text('SELECT id,issuer,jwks_uri,server_metadata_url,audiences,adapter_name,token_endpoint_auth_method,client_id,authorization_endpoint,token_endpoint,userinfo_endpoint FROM public.login_providers WHERE issuer=:issuer AND active=true'),{'issuer':issuer}).mappings().all()
        if len(rows)!=1:raise HTTPException(404,'Provider unavailable')
        value=dict(rows[0]);value['adapter_name']=value['adapter_name'] or 'oidc'
        return value
    async def read_permissions(request:Request):
        body=bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body)>65536:raise HTTPException(413,'Metadata request too large')
        try:payload=json.loads(body)
        except (ValueError,UnicodeError):raise HTTPException(400,'Invalid metadata request')
        if not isinstance(payload,dict):raise HTTPException(400,'Invalid metadata request')
        if request.url.path.endswith('/get_permissions_for_roles'):
            roles=payload.get('role_mnemonics')
            if not isinstance(roles,list) or len(roles)>64 or any(not isinstance(v,str) or not v or len(v)>256 for v in roles):raise HTTPException(400,'Bounded role list required')
        headers={k:request.headers[k] for k in ['authorization','cookie'] if k in request.headers}
        # These two existing IAM operations only read authorization metadata.
        # A fixed local origin and exact routes prevent an arbitrary proxy.
        async with httpx.AsyncClient(trust_env=False,timeout=10,follow_redirects=False) as client:
            response=await client.post('http://127.0.0.1:18110'+request.url.path,json=payload,headers=headers)
        return JSONResponse(response.json(),status_code=response.status_code,headers={'cache-control':'no-store'})
    app.add_api_route('/user-access/get_permissions_for_roles',read_permissions,methods=['POST'])
    app.add_api_route('/user-access/get_user_data_policies',read_permissions,methods=['POST'])
    return app

if os.environ.get('KDBT_IDENTITY_METADATA_SETTINGS'):app=build(json.loads(Path(os.environ['KDBT_IDENTITY_METADATA_SETTINGS']).read_text()))
