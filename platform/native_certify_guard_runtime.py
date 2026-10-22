"""Private fixed-upstream deployment of the Certify rollback token guard."""
import json
import os
import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import psycopg2
import uvicorn
from native_certify_failed_code_recovery import build_token_gateway
from native_remaining_three_fence import active as producers_fenced

BASE = Path('/opt/karnatakadbt/private/mosip-migration/remaining-three')


def load(path):
    path = Path(path).resolve(strict=True)
    if not path.is_relative_to(BASE) or path.stat().st_uid != 0 or path.stat().st_mode & 0o077:
        raise ValueError('Private root-owned guard settings required')
    settings = json.loads(path.read_text())
    upstream = urlsplit(settings['upstream'])
    if (upstream.scheme != 'http' or upstream.username or upstream.password or upstream.query or upstream.fragment
            or upstream.path != '/v1/certify/oauth/token' or upstream.port not in (None, 80)
            or ipaddress.ip_address(upstream.hostname) not in ipaddress.ip_network('10.43.0.0/16')
            or settings['listen'] != '10.42.0.1' or settings['port'] != 18156):
        raise ValueError('Pinned Karnataka production guard transport required')
    if not settings['connection']['dbname'].startswith('kdbt_native_certify_') or not settings['connection']['user'].startswith('kdbt_certify_guard_'):
        raise ValueError('Scoped retained authorization state required')

    def connect():
        return psycopg2.connect(**settings['connection'], connect_timeout=5,
            options='-c statement_timeout=5000 -c lock_timeout=5000')

    with connect() as connection, connection.cursor() as cursor:
        cursor.execute('SELECT id,kind,expires_at,used_at,tx_salt,tx_hash,attempts FROM certify.native_authorization LIMIT 0')
        cursor.execute('SELECT client_id,code_challenge,code_challenge_method,is_code_used,code_used_at FROM certify.iar_session LIMIT 0')

    def transport(method, headers, form=None, *, native=False):
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=20) as client:
            with client.stream(method, 'http://127.0.0.1:18147/v1/certify/oauth/token' if native else settings['upstream'], data=form,
                               headers={**headers, 'x-forwarded-proto': 'https'}) as result:
                data = bytearray()
                for chunk in result.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 1024 * 1024:
                        raise ValueError('Bounded token response required')
                return httpx.Response(result.status_code, content=bytes(data), headers=result.headers)

    native = {}
    if settings.get('native_authority_database'):
        from native_certify_token_ownership import CertifyTokenOwnership
        ownership = CertifyTokenOwnership(settings['native_authority_database'])
        native = {'native_owner': ownership.read,
                  'native_forward': lambda form, headers: transport('POST', headers, form, native=True),
                  'native_preflight_forward': lambda headers: transport('OPTIONS', headers, native=True)}
    app = build_token_gateway(connect, lambda form: transport('POST', {}, form),
        request_forward=lambda form, headers: transport('POST', headers, form),
        preflight_forward=lambda headers: transport('OPTIONS', headers), **native)

    @app.middleware('http')
    async def maintenance_boundary(request, call_next):
        if request.url.path != '/health' and producers_fenced():
            from starlette.responses import JSONResponse
            return JSONResponse({'error': 'temporarily_unavailable'}, status_code=503,
                                headers={'Cache-Control': 'no-store', 'Retry-After': '30'})
        return await call_next(request)

    @app.get('/health')
    def health():
        with connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        if settings.get('native_authority_database'):
            ownership.read()
        return {'status': 'UP', 'native_failed_code_guard': True, 'interactive_pkce_counter_recovery': True}

    return settings, app


if __name__ == '__main__':
    settings, app = load(os.environ['KDBT_CERTIFY_GUARD_SETTINGS'])
    uvicorn.run(app, host=settings['listen'], port=settings['port'], access_log=False, log_level='warning')
