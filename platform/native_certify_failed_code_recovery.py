"""Preserve native pre-authorized-code security state during reverse recovery.

The caller must route every token request through this guard, with the native
writer fenced and the retained SQL state available. This class does not grant
production admission or establish that routing. Forward must be a trusted,
fixed-origin transport; it receives no caller-selected destination.
"""
import hashlib
import hmac
import re
import time

PREAUTH = 'urn:ietf:params:oauth:grant-type:pre-authorized_code'


class RecoveryGrantRejected(ValueError):
    pass


class FailedCodeRecovery:
    def __init__(self, connect, forward):
        self.connect, self.forward = connect, forward

    def verify_projection(self, row):
        """Check counter coverage against retained SQL under an external fence.

        This verifies data, not routing. The coordinator must separately prove
        that requests cannot bypass this guard before installing a projection.
        """
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('''SELECT kind,expires_at,used_at,attempts
                FROM certify.native_authorization WHERE id=%s''', (row['id'],))
            value = cursor.fetchone()
        if value != (row['kind'], row['expires_at'], row['used_at'], row['attempts']):
            raise RecoveryGrantRejected('Recovery projection security state changed')

    def token(self, form, *, forward=None):
        forward = self.forward if forward is None else forward
        if not isinstance(form, dict) or len(form) > 16 or any(
                not isinstance(k, str) or not isinstance(v, str) or len(k) > 128 or len(v) > 4096
                for k, v in form.items()):
            raise RecoveryGrantRejected('invalid_request')
        grant = form.get('grant_type')
        if grant not in {PREAUTH, 'authorization_code'}:
            return forward(form)
        code = form.get('pre-authorized_code' if grant == PREAUTH else 'code', '')
        if not code or len(code) > 512:
            raise RecoveryGrantRejected('invalid_grant')
        identifier = hashlib.sha256(code.encode()).hexdigest()
        rejected = False
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('''SELECT kind,expires_at,used_at,tx_salt,tx_hash,attempts
                FROM certify.native_authorization WHERE id=%s FOR UPDATE''', (identifier,))
            row = cursor.fetchone()
            if row is not None:
                if row[0] != ('PREAUTH' if grant == PREAUTH else 'IAR') or row[1] <= time.time() or row[2] is not None or row[5] >= 5:
                    rejected = True
                else:
                    supplied = form.get('tx_code', '')
                    if len(supplied) > 128:
                        supplied = ''
                    invalid = row[4] is not None and not hmac.compare_digest(
                            hashlib.pbkdf2_hmac('sha256', supplied.encode(), bytes(row[3]), 600000), bytes(row[4]))
                    if grant == 'authorization_code':
                        cursor.execute('''SELECT client_id,code_challenge,code_challenge_method,is_code_used
                            FROM certify.iar_session WHERE authorization_code=%s''', (identifier,))
                        interactive = cursor.fetchall()
                        verifier = form.get('code_verifier', '')
                        encoded = __import__('base64').urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
                        invalid = invalid or (len(interactive) != 1 or interactive[0][2] != 'S256'
                            or interactive[0][3] or form.get('client_id') != interactive[0][0]
                            or re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier) is None
                            or not hmac.compare_digest(encoded, interactive[0][1]))
                    if invalid:
                        cursor.execute('UPDATE certify.native_authorization SET attempts=attempts+1 WHERE id=%s', (identifier,))
                        rejected = True
                    else:
                        # Commit consumption BEFORE forwarding. An uncertain transport
                        # outcome must never make a code redeemable a second time.
                        cursor.execute('UPDATE certify.native_authorization SET used_at=%s WHERE id=%s',
                                       (time.time(), identifier))
                        # Retained execution owns its SQL consumption timestamp.
                        # Its authenticated reverse import reconciles that value;
                        # the native journal already blocks native-side replay.
        # Raise outside the transaction so failed-attempt increments survive.
        if rejected:
            raise RecoveryGrantRejected('invalid_grant')
        return forward(form)


def build_token_gateway(connect, forward, *, request_forward=None, preflight_forward=None,
                        native_owner=None, native_forward=None, native_preflight_forward=None):
    """Bounded token-only HTTP boundary; configure transport outside the app.

    Run without access logging. Production routing/ownership changes are the
    responsibility of the coordinated handoff, not application startup.
    """
    from fastapi import FastAPI, Request
    from starlette.responses import JSONResponse, Response
    from starlette.concurrency import run_in_threadpool
    from urllib.parse import parse_qsl

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    if (native_owner is None) != (native_forward is None):
        raise ValueError('Native routing requires both an owner observer and fixed native transport')
    recovery = FailedCodeRecovery(connect, forward)
    headers = {'Cache-Control': 'no-store', 'Pragma': 'no-cache', 'X-KarnatakaDBT-Token-Guard': 'v1'}

    def selected_owner():
        owner = 'LEGACY' if native_owner is None else native_owner()
        if owner not in {'LEGACY', 'NATIVE'}:
            raise ValueError('Token writer ownership is fenced or unknown')
        return owner

    def response(result):
        if not 200 <= result.status_code < 300 and not 400 <= result.status_code < 600:
            return JSONResponse({'error': 'temporarily_unavailable'}, status_code=503, headers=headers)
        selected = {key: value for key, value in result.headers.items() if key.lower() in {
            'access-control-allow-origin', 'access-control-allow-credentials', 'access-control-allow-methods',
            'access-control-allow-headers', 'access-control-max-age', 'vary', 'www-authenticate', 'retry-after'}}
        return Response(result.content, status_code=result.status_code,
                        headers={**selected, **headers, 'Content-Type': 'application/json'})

    @app.options('/v1/certify/oauth/token')
    async def preflight(request: Request):
        if preflight_forward is None and native_preflight_forward is None:
            return Response(status_code=405, headers=headers)
        try:
            selected = native_preflight_forward if selected_owner() == 'NATIVE' else preflight_forward
            if selected is None:
                return Response(status_code=405, headers=headers)
            return response(await run_in_threadpool(selected, {
                key: request.headers[key] for key in ('origin', 'access-control-request-method', 'access-control-request-headers')
                if key in request.headers}))
        except Exception:
            return JSONResponse({'error': 'temporarily_unavailable'}, status_code=503, headers=headers)

    @app.post('/v1/certify/oauth/token')
    async def token(request: Request):
        if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/x-www-form-urlencoded':
            return JSONResponse({'error': 'invalid_request'}, status_code=400, headers=headers)
        try:
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 16384:
                    raise RecoveryGrantRejected('invalid_request')
            text = body.decode('ascii')
            if re.search(r'%(?![0-9a-fA-F]{2})', text):
                raise RecoveryGrantRejected('invalid_request')
            pairs = parse_qsl(text, keep_blank_values=True, strict_parsing=True, max_num_fields=16,
                              encoding='utf-8', errors='strict')
            form = dict(pairs)
            if len(form) != len(pairs):
                raise RecoveryGrantRejected('invalid_request')
        except (ValueError, UnicodeError):
            return JSONResponse({'error': 'invalid_request'}, status_code=400, headers=headers)
        try:
            if selected_owner() == 'NATIVE':
                # Native authorization performs the atomic attempt/consumption
                # transaction itself. Running the retained SQL guard first
                # would consume the code twice and reject a valid redemption.
                result = await run_in_threadpool(native_forward, form, {
                    key: request.headers[key] for key in ('authorization', 'origin', 'cookie') if key in request.headers})
                return response(result)
            transport = None if request_forward is None else lambda value: request_forward(value, {
                key: request.headers[key] for key in ('authorization', 'origin', 'cookie') if key in request.headers})
            result = await run_in_threadpool(recovery.token, form, forward=transport)
            # Never relay cookies, redirects or arbitrary upstream headers.
            return response(result)
        except RecoveryGrantRejected as error:
            return JSONResponse({'error': str(error)}, status_code=400, headers=headers)
        except Exception:
            # Retained SQL failure must never bypass validation. A transport
            # failure after committed consumption also remains fail closed.
            return JSONResponse({'error': 'temporarily_unavailable'}, status_code=503, headers=headers)

    return app
