"""Bounded, authenticated read lookups for the IAM policy editor."""
import datetime,uuid
import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from registry_metadata_api import RegistryAuthError

LOOKUPS={
 'registers':('registry','/register-metadata/get_all_registers',()),
 'register-fields':('registry','/register-metadata/get_register_fields',('register_id',)),
 'registry-attributes':('registry','/register-metadata/get_register_schema',('register_id',)),
 'geo-levels':('master','/geo/get_all_geo_levels',()),
 'geo-values':('master','/geo/get_geo_level_values',('level_id',)),
 'attributes':('master','/attributes/get_all_attributes',()),
 'attribute-values':('master','/attributes/get_attribute_values',('attribute_id',))}

def mount_iam_catalogue(app,authority,*,transport=None):
    origins={'registry':'http://127.0.0.1:18120','master':'http://127.0.0.1:18121'}
    @app.get('/console/catalogue/{kind}')
    async def catalogue(kind:str,request:Request):
        principal=await authority(request)
        if 'dataPolicy:create' not in principal.permissions:raise RegistryAuthError(403,'Policy creation access required')
        if kind not in LOOKUPS:return JSONResponse({'error':'Unknown catalogue'},status_code=404)
        service,path,fields=LOOKUPS[kind];payload={}
        for field in fields:
            value=request.query_params.get(field,'')
            if not value or len(value)>255:return JSONResponse({'error':'Required catalogue identifier missing'},status_code=422)
            payload[field]=value
        body={'request_header':{'sender_app_mnemonic':'KDBT_NATIVE_IAM','sender_app_url':'https://localhost:8445','request_id':str(uuid.uuid4()),'request_timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat()},'request_body':{'request_payload':payload,'pagination_request':{'current_page':1,'page_size':100,'search_text':''}}}
        # The destination's browser-compatible read envelope also requires a
        # double-submit value. Identity and permissions remain bearer-verified.
        binding=uuid.uuid4().hex
        headers={'authorization':'Bearer '+request.state.administration_bearer,'x-csrf-token':binding}
        try:
            async with httpx.AsyncClient(trust_env=False,transport=transport,timeout=10,follow_redirects=False) as client:
                async with client.stream('POST',origins[service]+path,headers=headers,cookies={'X-CSRF-Token':binding},json=body) as response:
                    if response.status_code in {401,403}:return JSONResponse({'error':'Catalogue access is not assigned'},status_code=response.status_code)
                    response.raise_for_status();content=b''
                    async for chunk in response.aiter_bytes():
                        content+=chunk
                        if len(content)>4*1024*1024:raise ValueError('Catalogue response exceeds limit')
            value=__import__('json').loads(content)
            if value.get('response_header',{}).get('response_status')!='SUCCESS':raise ValueError('Catalogue operation failed')
            result=JSONResponse(value['response_body']['response_payload'],headers={'cache-control':'no-store'})
            for cookie in getattr(request.state,'registry_auth_cookies',[]):result.headers.append('set-cookie',cookie)
            return result
        except (httpx.HTTPError,ValueError,KeyError):return JSONResponse({'error':'Policy catalogue temporarily unavailable'},status_code=503,headers={'cache-control':'no-store'})
