"""Route native OAuth transactions while draining existing IAM transactions.

Only three authentication endpoints are exposed. SQL business APIs continue
through their existing owners. Redis sessions keep the installed wire format.
"""
import json,os
from pathlib import Path
import httpx,redis
from fastapi import FastAPI,Request
from fastapi.responses import Response,JSONResponse

def build(settings):
    cache=redis.from_url(settings['redis_url'],decode_responses=True,socket_timeout=5,socket_connect_timeout=5)
    app=FastAPI(title='KarnatakaDBT native IAM callback admission')
    @app.get('/health')
    def health():return {'ready':bool(cache.ping()),'legacy_business_writer_retained':True}
    @app.api_route('/auth/start_authentication_transaction',methods=['POST'])
    @app.api_route('/auth/callback',methods=['GET'])
    @app.api_route('/auth/backchannel-logout',methods=['POST'])
    async def route(request:Request):
        native=True
        if request.url.path=='/auth/callback':
            state=request.query_params.get('state','')
            if len(state)>1024:return JSONResponse({'error':'Authentication rejected'},status_code=401)
            try:
                value=json.loads(cache.get('auth_tx:'+state) or '{}')
                native=bool((value.get('context') or {}).get('browser_binding'))
            except (ValueError,TypeError):return JSONResponse({'error':'Authentication rejected'},status_code=401)
        origin=settings['native_origin'] if native else settings['legacy_origin']
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>65536:return JSONResponse({'error':'Authentication request too large'},status_code=413)
        headers={key:value for key,value in request.headers.items() if key.lower() in {'cookie','content-type','origin','authorization','x-csrf-token'}}
        try:
            async with httpx.AsyncClient(trust_env=False,timeout=25,follow_redirects=False) as client:
                result=await client.request(request.method,origin+request.url.path,params=request.query_params,content=bytes(body),headers=headers)
        except httpx.HTTPError:return JSONResponse({'error':'Authentication service unavailable'},status_code=503)
        response=Response(result.content,status_code=result.status_code)
        for key,value in result.headers.multi_items():
            if key.lower() in {'content-type','location','set-cookie','cache-control','x-content-type-options'}:response.headers.append(key,value)
        response.headers['cache-control']='no-store';response.headers['X-KarnatakaDBT-IAM-Callback']='native' if native else 'legacy-transaction-drain'
        return response
    return app

if os.environ.get('KDBT_IAM_CALLBACK_SETTINGS'):app=build(json.loads(Path(os.environ['KDBT_IAM_CALLBACK_SETTINGS']).read_text()))
