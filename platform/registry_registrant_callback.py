"""Explicit state-authenticated GET callback; it never bypasses console guards."""
import html
import secrets
from fastapi import Request, Query
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool
from registry_metadata_store import RegistryError
from registry_registrant_auth_store import CALLBACK_PATH


def install_registrant_callback(app, store, audit):
    @app.get(CALLBACK_PATH, response_class=HTMLResponse)
    async def registrant_callback(request: Request, code: str = Query(...), state: str = Query(...)):
        try:
            key = await run_in_threadpool(audit.begin, CALLBACK_PATH, 'GET')
        except Exception:
            return HTMLResponse('Authentication audit storage is unavailable.', status_code=503,
                                headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})
        result = None
        try:
            result = await run_in_threadpool(store.complete_registrant_authentication, state, code)
            status = result['status']
            title = 'Authentication Successful' if status == 'SUCCESS' else 'Authentication Failed'
            reason = result.get('failure_reason') or ''
        except RegistryError as error:
            status, title, reason = 'FAILURE', 'Authentication Error', error.message
        except Exception:
            status, title, reason = 'FAILURE', 'Authentication Error', 'Authentication completion failed.'
        try:
            await run_in_threadpool(audit.finish, key, None, 200, status != 'SUCCESS')
        except Exception:
            # A committed authentication result must never be made retryable.
            pass
        nonce = secrets.token_urlsafe(18)
        identifier = result['authentication_id'] if result else 'N/A'
        document = f'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style nonce="{nonce}">body{{font:16px system-ui;min-height:90vh;display:grid;place-items:center}}
main{{max-width:32rem;padding:2rem;border:1px solid #ddd;border-radius:12px}}dd{{overflow-wrap:anywhere}}
button{{padding:.8rem 1.5rem;cursor:pointer}}h1{{font-size:1.5rem}}</style>
<main><h1>{title}</h1><dl><dt>Authentication ID:</dt><dd>{html.escape(identifier)}</dd>
<dt>Status:</dt><dd>{status}</dd></dl><p>{html.escape(reason)}</p><button id="close">Close Window</button></main>
<script nonce="{nonce}">document.getElementById('close').onclick=()=>window.close();
{'setTimeout(()=>window.close(),10000);' if status == 'SUCCESS' else ''}</script></html>'''
        return HTMLResponse(document, headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
            'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': f"default-src 'none'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; frame-ancestors 'none'; base-uri 'none'"})
