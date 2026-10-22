"""Native login assets and a fixed-origin same-site authorization proxy."""
import io
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import qrcode
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response


def build(settings):
    prefix = settings.get('public_prefix', '')
    if prefix and not re.fullmatch(r'/[a-zA-Z0-9/_-]+', prefix):
        raise ValueError('Invalid login prefix')
    origin = settings['authorization_origin']
    parsed = urlsplit(origin)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.port != 18144 or parsed.path:
        raise ValueError('The login proxy requires the local native authorization service')
    assets = Path(settings['assets']).resolve()
    app = FastAPI(title='KarnatakaDBT native login', docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def privacy(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = ("default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self' http://127.0.0.1:*; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        return response

    @app.get(prefix + '/')
    @app.get(prefix + '/authorize')
    def authorize():
        html = (assets / 'index.html').read_text()
        html = html.replace('<body>', '<body data-service-prefix="' + prefix + '">')
        html = html.replace('href="/assets/', 'href="' + prefix + '/assets/').replace('src="/assets/', 'src="' + prefix + '/assets/')
        return HTMLResponse(html)

    @app.get(prefix + '/assets/{name}')
    def asset(name: str):
        allowed = {'login.css': 'text/css', 'login.js': 'application/javascript'}
        if name not in allowed:
            return Response(status_code=404)
        return Response((assets / name).read_bytes(), media_type=allowed[name])

    @app.get(prefix + '/_native/qr')
    def qr(text: str):
        if len(text) > 2048 or not text.startswith(('inji:', 'https:')):
            return JSONResponse({'error': 'invalid_wallet_link'}, status_code=400)
        buffer = io.BytesIO()
        qrcode.make(text, box_size=5, border=3).save(buffer, format='PNG')
        return Response(buffer.getvalue(), media_type='image/png')

    @app.api_route(prefix + '/v1/esignet/{path:path}', methods=['GET', 'POST', 'PUT'])
    async def authorization_proxy(path: str, request: Request):
        if path.startswith('/') or any(value in path for value in ['..', '\\', '//']):
            return Response(status_code=400)
        body = bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body) > 1024 * 1024:
                return Response(status_code=413)
        if len(request.headers.getlist('x-kdbt-private-rehearsal'))>1:return Response(status_code=400)
        allowed_headers = {'content-type', 'authorization', 'cookie', 'x-xsrf-token', 'oauth-details-key', 'oauth-details-hash','x-kdbt-private-rehearsal'}
        headers = {key: value for key, value in request.headers.items() if key.lower() in allowed_headers}
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=40) as client:
                result = await client.request(request.method, origin + '/v1/esignet/' + path,
                                              params=request.query_params, content=bytes(body), headers=headers)
            response = Response(result.content, status_code=result.status_code,
                                media_type=result.headers.get('content-type', 'application/json').split(';')[0])
            for cookie in result.headers.get_list('set-cookie'):
                if prefix:
                    cookie = re.sub(r'(?i)(;\s*path=)/(?=;|$)', lambda match: match[1] + prefix, cookie)
                response.headers.append('set-cookie', cookie)
            return response
        except httpx.HTTPError:
            return JSONResponse({'errors': [{'errorCode': 'authorization_unavailable'}]}, status_code=503)

    @app.get('/health')
    def health():
        return {'ready': True, 'native_login_ui': True, 'production_acceptance_verified': False}

    return app


if os.environ.get('KDBT_NATIVE_LOGIN_SETTINGS'):
    app = build(json.loads(Path(os.environ['KDBT_NATIVE_LOGIN_SETTINGS']).read_text()))
