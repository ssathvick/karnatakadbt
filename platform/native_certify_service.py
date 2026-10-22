"""Native Certify candidate. Only implemented, testable operations are exposed.

Shared native crypto runs in-process; no legacy business API is contacted.
Credential configuration, issuance and recovery require separate acceptance.
"""
import base64
import datetime
import hmac
import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from native_keymanager_service import build as crypto_application, OPERATIONS as KEY_OPERATIONS
from native_keymanager import VaultFailure, stamp
from native_certify_crypto import CertifyCrypto
from native_certify_configuration import CertifyConfiguration
from native_certify_records import CertifyRecords
from native_certify_authorization import CertifyAuthorization, CredentialAuthorizationFailure
from native_certify_issuance import CertifyIssuance
from native_certify_interactive import CertifyInteractive
from native_certify_admin import CertifyAdministrator
from native_certify_activation import admit
from urllib.parse import parse_qs


PREFIX = '/v1/certify'
OPERATIONS = {
    'uploadSignedCertificate': ('POST', '/system-info/uploadCertificate', 'uploadCertificate'),
    'uploadCACertificate': ('POST', '/system-info/upload-ca-certificate', 'uploadCACertificate'),
    'generateCSR': ('POST', '/system-info/generate-csr', 'generateCSR'),
    'getCertificate': ('GET', '/system-info/certificate', 'getCertificate'),
    'sign': ('POST', '/sign', 'sign'), 'validate': ('POST', '/validate', 'validate'),
    'signPDF': ('POST', '/pdf/sign', 'signPDF'),
    'jwtEncrypt': ('POST', '/jwtEncrypt', 'jwtEncrypt'), 'jwtDecrypt': ('POST', '/jwtDecrypt', 'jwtDecrypt'),
    'encrypt': ('POST', '/encrypt', 'encrypt'), 'decrypt': ('POST', '/decrypt', 'decrypt'),
    'encryptWithPin': ('POST', '/encryptWithPin', 'encryptWithPin'),
    'decryptWithPin': ('POST', '/decryptWithPin', 'decryptWithPin'),
    'generateArgon2Hash': ('POST', '/generateArgon2Hash', 'generateArgon2Hash'),
    'signV2': ('POST', '/signV2', None), 'signRawData': ('POST', '/signRawData', None),
    'jwtSign': ('POST', '/jwtSign', None), 'jwtSignV2': ('POST', '/jwtSign/v2', None),
    'jwsSign': ('POST', '/jwsSign', None), 'jwsSignV2': ('POST', '/jwsSign/v2', None),
    'jwtVerify': ('POST', '/jwtVerify', None), 'jwtVerifyV2': ('POST', '/jwtVerify/v2', None),
    'coseSign1': ('POST', '/coseSign1', None), 'coseVerify1': ('POST', '/coseVerify1', None),
    'cwtSign': ('POST', '/cwtSign', None), 'cwtVerify': ('POST', '/cwtVerify', None),
}
BUSINESS_OPERATIONS = {
    'createConfiguration': ('POST', '/credential-configurations'),
    'getConfiguration': ('GET', '/credential-configurations/{credentialConfigKeyId}'),
    'updateConfiguration': ('PUT', '/credential-configurations/{credentialConfigKeyId}'),
    'deleteConfiguration': ('DELETE', '/credential-configurations/{credentialConfigKeyId}'),
    'issuerMetadata': ('GET', '/.well-known/openid-credential-issuer'),
    'legacyIssuerMetadata': ('GET', '/issuance/.well-known/openid-credential-issuer'),
    'oauthMetadata': ('GET', '/.well-known/oauth-authorization-server'),
    'jwks': ('GET', '/.well-known/jwks.json'),
    'did': ('GET', '/.well-known/did.json'),
    'legacyDid': ('GET', '/issuance/.well-known/did.json'),
    'ledgerSearch': ('POST', '/ledger-search'),
    'ledgerSearchV2': ('POST', '/v2/ledger-search'),
    'statusList': ('GET', '/credentials/status-list/{id}'),
    'renderingTemplate': ('GET', '/rendering-template/{id}'),
}
AUTHORIZATION_OPERATIONS = {
    'preAuthorizedData': ('POST', '/pre-authorized-data'),
    'credentialOffer': ('GET', '/credential-offer-data/{offer_id}'),
    'credentialToken': ('POST', '/oauth/token'),
    'interactiveAuthorization': ('POST', '/oauth/iar'),
}
ISSUANCE_OPERATIONS = {
    'issueCredential': ('POST', '/issuance/credential'),
    'issueCredentialV11': ('POST', '/issuance/vd11/credential'),
    'issueCredentialV12': ('POST', '/issuance/vd12/credential'),
    'updateCredentialStatus': ('POST', '/credentials/status'),
    'updateCredentialStatusV2': ('POST', '/credentials/v2/status'),
}


def build(settings):
    rehearsal = admit(settings, Path(__file__).parent)
    crypto_settings = settings['crypto']
    internal_token = settings['inprocess_crypto_token']
    permissions = sorted(set(operation[2] for operation in KEY_OPERATIONS.values()))
    crypto_settings = {**crypto_settings, 'owner': settings['environment'], 'principals': [{'token': internal_token, 'permissions': permissions,
                       'applications': list(crypto_settings['policies']), 'domains': settings['trust_domains']}]}
    internal = crypto_application(crypto_settings)
    engine = internal.state.engine
    crypto = CertifyCrypto(engine, crypto_settings)
    app = FastAPI(title='KarnatakaDBT native credential crypto candidate', docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine, app.state.crypto = engine, crypto
    administrator = CertifyAdministrator(settings['staff_administrator']) if settings.get('staff_administrator') else None

    def privileged(token):
        # Candidate fixtures remain isolated; production activation is separately fenced.
        return bool(token and ((settings['environment'] == 'CANDIDATE' and hmac.compare_digest(token, settings['candidate_token'])) or
                               administrator and administrator.authorize(token)))

    def envelope(value=None, error=None):
        return {'id': None, 'version': '1.0', 'responsetime': stamp(datetime.datetime.now(datetime.timezone.utc)),
                'response': value, 'errors': [] if error is None else [{'errorCode': error, 'message': 'Request rejected'}]}

    @app.middleware('http')
    async def boundary(request, call_next):
        health = request.url.path in ['/health', PREFIX + '/actuator/health']
        if not health:
            if rehearsal and not rehearsal.allows(request):
                return JSONResponse(envelope(error='rehearsal_fenced'), status_code=503)
            with engine.vault.connect() as connection:
                if connection.execute('SELECT owner FROM km_authority WHERE id=1').fetchone()[0] != settings['environment']:
                    return JSONResponse(envelope(error='writer_fenced'), status_code=503)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-KarnatakaDBT-Credential-Backend'] = 'native' if settings['environment'] == 'NATIVE' else 'native-candidate'
        return response

    def handler(operation):
        async def invoke(request: Request):
            header = request.headers.get('authorization', '')
            supplied = header[7:] if header.startswith('Bearer ') else ''
            if not await run_in_threadpool(privileged, supplied):
                return JSONResponse(envelope(error='access_denied'), status_code=401)
            body = bytearray()
            async for part in request.stream():
                body.extend(part)
                if len(body) > (12 * 1024 * 1024 if operation == 'signPDF' else 1024 * 1024):
                    return JSONResponse(envelope(error='request_too_large'), status_code=413)
            mapped = OPERATIONS[operation][2]
            if mapped:
                method, path, permission = KEY_OPERATIONS[mapped]
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=internal), base_url='http://native-crypto') as client:
                    response = await client.request(method, '/v1/keymanager' + path, params=request.query_params,
                                                    content=bytes(body), headers={'Authorization': 'Bearer ' + internal_token,
                                                    'Content-Type': 'application/json'})
                return Response(response.content, status_code=response.status_code, media_type='application/json')
            try:
                value = json.loads(body).get('request')
                if not isinstance(value, dict):
                    raise VaultFailure('Request object required')
                if value.get('validateTrust') and value.get('domain') not in settings['trust_domains']:
                    return JSONResponse(envelope(error='trust_domain_denied'), status_code=403)
                def dispatch():
                    if operation in ['jwtSign', 'jwtSignV2', 'jwsSign', 'jwsSignV2']:
                        return crypto.jws_sign(value, jws=operation.startswith('jws'))
                    if operation in ['jwtVerify', 'jwtVerifyV2']:
                        return crypto.jws_verify(value)
                    if operation in ['signV2', 'signRawData']:
                        return crypto.raw_sign(value, detailed=operation == 'signRawData')
                    if operation in ['coseSign1', 'cwtSign']:
                        return crypto.cose_sign(value, cwt=operation == 'cwtSign')
                    if operation in ['coseVerify1', 'cwtVerify']:
                        return crypto.cose_verify(value, cwt=operation == 'cwtVerify')
                    raise VaultFailure('Unknown crypto operation')
                return JSONResponse(envelope(await run_in_threadpool(dispatch)))
            except (VaultFailure, ValueError, TypeError, KeyError):
                return JSONResponse(envelope(error='invalid_crypto_request'), status_code=400)
        return invoke

    for operation, (method, path, _) in OPERATIONS.items():
        app.add_api_route(PREFIX + path, handler(operation), methods=[method], name=operation)

    if settings.get('business'):
        configuration = CertifyConfiguration(settings['business'], engine)
        records = CertifyRecords(configuration)
        app.state.configuration = configuration

        def business_handler(operation):
            async def invoke(request: Request):
                public = operation in ['issuerMetadata', 'legacyIssuerMetadata', 'oauthMetadata', 'jwks', 'did', 'legacyDid', 'statusList', 'renderingTemplate']
                header = request.headers.get('authorization', '')
                supplied = header[7:] if header.startswith('Bearer ') else ''
                if not public and not await run_in_threadpool(privileged, supplied):
                    return JSONResponse(envelope(error='access_denied'), status_code=401)
                try:
                    body = bytearray()
                    async for part in request.stream():
                        body.extend(part)
                        if len(body) > 1024 * 1024:
                            return JSONResponse(envelope(error='request_too_large'), status_code=413)
                    def dispatch():
                        if operation in ['ledgerSearch', 'ledgerSearchV2']:
                            return records.search(json.loads(body), version=2 if operation == 'ledgerSearchV2' else 1)
                        if operation in ['statusList', 'renderingTemplate']:
                            return records.retained(request.path_params['id'], template=operation == 'renderingTemplate')
                        if operation in ['issuerMetadata', 'legacyIssuerMetadata']:
                            return configuration.metadata(legacy=operation == 'legacyIssuerMetadata')
                        if operation == 'oauthMetadata':
                            return configuration.oauth_metadata()
                        if operation == 'jwks':
                            return configuration.jwks()
                        if operation in ['did', 'legacyDid']:
                            return configuration.did()
                        identifier = request.path_params.get('credentialConfigKeyId')
                        if operation == 'getConfiguration':
                            return configuration.response(configuration.get(identifier))
                        if operation == 'deleteConfiguration':
                            return configuration.delete(identifier)
                        value = json.loads(body)
                        if operation == 'createConfiguration':
                            created = configuration.save(value)
                            return {'id': created['credentialConfigKeyId'], 'status': 'SUCCESS'}
                        updated = configuration.update(identifier, value)
                        return {'id': updated['credentialConfigKeyId'], 'status': 'SUCCESS'}
                    result = await run_in_threadpool(dispatch)
                    if operation in ['statusList', 'renderingTemplate']:
                        return Response(result, media_type='image/svg+xml' if operation == 'renderingTemplate' else 'application/json',
                                        headers={'Content-Security-Policy': "default-src 'none'; sandbox", 'X-Content-Type-Options': 'nosniff'})
                    return JSONResponse(result)
                except (VaultFailure, ValueError, TypeError, KeyError):
                    return JSONResponse(envelope(error='invalid_configuration_request'), status_code=400)
            return invoke

        for operation, (method, path) in BUSINESS_OPERATIONS.items():
            app.add_api_route(PREFIX + path, business_handler(operation), methods=[method], name=operation)

        if settings.get('authorization'):
            authorization = CertifyAuthorization(configuration, crypto, settings['authorization'])
            app.state.authorization = authorization

            def authorization_handler(operation):
                async def invoke(request: Request):
                    header = request.headers.get('authorization', '')
                    supplied = header[7:] if header.startswith('Bearer ') else ''
                    if operation == 'preAuthorizedData' and not await run_in_threadpool(privileged, supplied):
                        return JSONResponse({'error': 'access_denied'}, status_code=401)
                    try:
                        body = bytearray()
                        async for part in request.stream():
                            body.extend(part)
                            if len(body) > 1024 * 1024:
                                raise CredentialAuthorizationFailure('invalid_request', status=413)
                        def dispatch():
                            if operation == 'preAuthorizedData':
                                return authorization.create_offer(json.loads(body))
                            if operation == 'credentialOffer':
                                return authorization.offer(request.path_params['offer_id'])
                            if request.headers.get('content-type', '').split(';')[0].strip() != 'application/x-www-form-urlencoded':
                                raise CredentialAuthorizationFailure('invalid_request')
                            values = parse_qs(body.decode('utf-8'), keep_blank_values=True, max_num_fields=30)
                            if any(len(value) != 1 for value in values.values()):
                                raise CredentialAuthorizationFailure('invalid_request')
                            form = {key: value[0] for key, value in values.items()}
                            if operation == 'interactiveAuthorization':
                                if not settings.get('issuance'):
                                    raise CredentialAuthorizationFailure('temporarily_unavailable', status=503)
                                return app.state.interactive.handle(form)
                            return authorization.token(form)
                        return JSONResponse(await run_in_threadpool(dispatch))
                    except CredentialAuthorizationFailure as error:
                        return JSONResponse({'error': error.error, **error.extra}, status_code=error.status)
                    except (VaultFailure, ValueError, TypeError, KeyError):
                        return JSONResponse({'error': 'invalid_request'}, status_code=400)
                return invoke

            for operation, (method, path) in AUTHORIZATION_OPERATIONS.items():
                app.add_api_route(PREFIX + path, authorization_handler(operation), methods=[method], name=operation)

            if settings.get('issuance'):
                issuance = CertifyIssuance(authorization, settings['issuance'])
                app.state.issuance = issuance
                app.state.interactive = CertifyInteractive(issuance)

                async def issue_credential(request: Request):
                    supplied = request.headers.get('authorization', '')
                    if not supplied.startswith('Bearer ') or len(supplied) > 16384:
                        return JSONResponse({'error': 'invalid_token'}, status_code=401)
                    status_update = request.url.path in [PREFIX + '/credentials/status', PREFIX + '/credentials/v2/status']
                    if status_update and not await run_in_threadpool(privileged, supplied.removeprefix('Bearer ')):
                        return JSONResponse({'error': 'access_denied'}, status_code=403)
                    try:
                        body = bytearray()
                        async for part in request.stream():
                            body.extend(part)
                            if len(body) > 1024 * 1024:
                                raise CredentialAuthorizationFailure('invalid_credential_request', status=413)
                        if status_update:
                            return JSONResponse(await run_in_threadpool(issuance.status.update, json.loads(body),
                                version=2 if request.url.path.endswith('/v2/status') else 1))
                        return JSONResponse(await run_in_threadpool(issuance.issue, json.loads(body), supplied.removeprefix('Bearer ')))
                    except CredentialAuthorizationFailure as error:
                        return JSONResponse({'error': error.error, **error.extra}, status_code=error.status)
                    except (VaultFailure, ValueError, TypeError, KeyError):
                        return JSONResponse({'error': 'invalid_credential_request'}, status_code=400)

                for operation, (method, path) in ISSUANCE_OPERATIONS.items():
                    app.add_api_route(PREFIX + path, issue_credential, methods=[method], name=operation)

    @app.get('/health')
    def health():
        return {'status': 'UP', 'environment': settings['environment'], 'native_certify_crypto': True,
                'candidate_operation_routes': len(OPERATIONS) + (len(BUSINESS_OPERATIONS) if settings.get('business') else 0) + (len(AUTHORIZATION_OPERATIONS) if settings.get('authorization') else 0) + (len(ISSUANCE_OPERATIONS) if settings.get('issuance') else 0), 'complete_certify_acceptance': settings['environment'] == 'NATIVE' and rehearsal is None,
                'private_fenced_rehearsal': rehearsal is not None,
                'production_cutover_verified': False}

    @app.get(PREFIX + '/v3/api-docs')
    def contract():
        source = json.loads(Path(settings['contract']).read_text())
        paths = {path for method, path, mapped in OPERATIONS.values()}
        if settings.get('business'):
            paths.update(path for method, path in BUSINESS_OPERATIONS.values())
        if settings.get('authorization'):
            paths.update(path for method, path in AUTHORIZATION_OPERATIONS.values())
        if settings.get('issuance'):
            paths.update(path for method, path in ISSUANCE_OPERATIONS.values())
        source['paths'] = {path: value for path, value in source['paths'].items() if path in paths}
        source['info']['title'] = 'KarnatakaDBT native credential crypto candidate'
        return source

    if settings.get('console'):
        if administrator is None:raise ValueError('Verified staff administrator policy required for console')
        from native_certify_console import mount_console
        console_operations={'crypto':OPERATIONS}
        for group,key,values in [('configuration','business',BUSINESS_OPERATIONS),
            ('authorization','authorization',AUTHORIZATION_OPERATIONS),('issuance','issuance',ISSUANCE_OPERATIONS)]:
            if settings.get(key):console_operations[group]=values
        mount_console(app,settings['console'],administrator,console_operations)
    return app


if os.environ.get('KDBT_NATIVE_CERTIFY_SETTINGS'):
    app = build(json.loads(Path(os.environ['KDBT_NATIVE_CERTIFY_SETTINGS']).read_text()))
