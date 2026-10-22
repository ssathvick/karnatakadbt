"""Authenticated native Keymanager candidate API; no legacy HTTP forwarding."""
import asyncio, base64, datetime, hmac, json, os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from native_keymanager import NativeKeymanager, stamp, VaultFailure
import native_keymanager_jose as jose
from native_keymanager_aux import Auxiliary
from native_keymanager_wire import client_operation,hybrid,token_id
from native_keymanager_migration import RecordCrypto,import_base
from starlette.concurrency import run_in_threadpool
from native_keymanager_auth import KeymanagerIdentity

PREFIX = '/v1/keymanager'
OPERATIONS = {
    'generateMasterKey': ('POST', '/generateMasterKey/{objectType}', 'manage'),
    'generateCSR': ('POST', '/generateCSR', 'manage'),
    'getCertificate': ('GET', '/getCertificate', 'read'),
    'getAllCertificates': ('GET', '/getAllCertificates', 'read'),
    'uploadCertificate': ('POST', '/uploadCertificate', 'manage'),
    'uploadOtherDomainCertificate': ('POST', '/uploadOtherDomainCertificate', 'manage'),
    'revokeKey': ('PUT', '/revokeKey', 'manage'),
    'uploadCACertificate': ('POST', '/uploadCACertificate', 'manage-trust'),
    'verifyCertificateTrust': ('POST', '/verifyCertificateTrust', 'read-trust'),
    'jwtSign': ('POST', '/jwtSign', 'sign'),
    'jwsSign': ('POST', '/jwsSign', 'sign'),
    'jwtVerify': ('POST', '/jwtVerify', 'verify'),
    'jwtEncrypt': ('POST', '/jwtEncrypt', 'encrypt'),
    'jwtDecrypt': ('POST', '/jwtDecrypt', 'decrypt'),
    'encryptWithPin': ('POST','/encryptWithPin','encrypt-pin'),
    'decryptWithPin': ('POST','/decryptWithPin','decrypt-pin'),
    'generateArgon2Hash': ('POST','/generateArgon2Hash','hash'),
    'generateSymmetricKey': ('POST','/generateSymmetricKey','manage'),
    'sign': ('POST','/sign','sign'),
    'validate': ('POST','/validate','verify'),
    'generateLicenseKey': ('POST','/license/generate','manage-license'),
    'mapLicenseKey': ('POST','/license/permission','manage-license'),
    'fetchLicenseKeyPermissions': ('GET','/license/permission','read-license'),
    'uploadPartnerCertificate': ('POST','/uploadPartnerCertificate','manage-partner'),
    'getPartnerCertificate': ('GET','/getPartnerCertificate/{partnerCertId}','read-partner'),
    'getPartnerSignedCertificate': ('GET','/getPartnerSignedCertificate/{partnerCertId}','read-partner'),
    'getSigningPublicKey': ('POST','/tpmsigning/publickey','read-client-key'),
    'getEncPublicKey': ('POST','/tpmencryption/publickey','read-client-key'),
    'tpmEncrypt': ('POST','/tpmencrypt','encrypt-client'),
    'tpmDecrypt': ('POST','/tpmdecrypt','decrypt-client'),
    'signData': ('POST','/cssign','sign-client'),
    'verifySignature': ('POST','/csverifysign','verify-client'),
    'encrypt': ('POST','/encrypt','encrypt'),
    'decrypt': ('POST','/decrypt','decrypt'),
    'generateTokenID': ('GET','/tokenid/{uin}/{partnercode}','token'),
    'zkEncrypt': ('POST','/zkEncrypt','encrypt-zk'),
    'zkDecrypt': ('POST','/zkDecrypt','decrypt-zk'),
    'zkReEncryptRandomKey': ('POST','/zkReEncryptRandomKey','rewrap-zk'),
    'getZKTempCertificate': ('GET','/getZKTempCertificate','migrate-zk'),
    'migrateZKKeys': ('POST','/migrateZKKeys','migrate-zk'),
    'migrateBaseKey': ('POST','/migrateBaseKey','migrate-base'),
    'signPDF': ('POST','/pdf/sign','sign-pdf'),
}


def build(settings):
    if settings.get('owner') not in {'CANDIDATE','NATIVE','LEGACY'}:
        raise ValueError('An explicit authority owner is required')
    engine = NativeKeymanager(settings['database'], base64.b64decode(settings['master_key'], validate=True), settings['policies'])
    aux = Auxiliary(engine,settings)
    records=RecordCrypto(aux)
    slots=asyncio.Semaphore(settings.get('max_crypto_jobs',2))
    app = FastAPI(title='KarnatakaDBT native key lifecycle candidate', version='1.0', docs_url=None, redoc_url=None, openapi_url=PREFIX+'/v3/api-docs')
    app.state.engine = engine
    identity=KeymanagerIdentity(settings['identity']) if settings.get('identity') else None
    with engine.vault.connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS km_authority(id INTEGER PRIMARY KEY CHECK(id=1),owner TEXT NOT NULL)')
        c.execute('INSERT OR IGNORE INTO km_authority VALUES(1,?)',(settings['owner'],))

    @app.middleware('http')
    async def ownership(request,call_next):
        if request.method not in {'GET','HEAD','OPTIONS'} or request.url.path==PREFIX+'/getZKTempCertificate':
            with engine.vault.connect() as c:owner=c.execute('SELECT owner FROM km_authority WHERE id=1').fetchone()[0]
            if owner=='LEGACY':return JSONResponse({'response':None,'errors':[{'errorCode':'writer_fenced','message':'Authority handoff in progress'}]},status_code=503)
        response=await call_next(request)
        response.headers['X-KarnatakaDBT-Keymanager-Backend']='native'
        response.headers['Cache-Control']='no-store'
        return response

    def envelope(value=None, error=None):
        return {'id': None, 'version': '1.0', 'responsetime': stamp(datetime.datetime.now(datetime.timezone.utc)),
                'response': value, 'errors': [{'errorCode': error, 'message': 'Request rejected'}] if error else []}

    def endpoint(operation):
        async def invoke(request: Request):
            supplied = request.headers.get('Authorization', '').removeprefix('Bearer ')
            principal = None
            permission = OPERATIONS[operation][2]
            for candidate in settings['principals']:
                if supplied and hmac.compare_digest(supplied, candidate['token']):
                    principal = candidate
            if principal is None and identity is not None and supplied:
                try:principal=await run_in_threadpool(identity.authorize,supplied,operation,permission,list(settings['policies']))
                except VaultFailure as error:
                    return JSONResponse(envelope(error='permission_denied' if str(error)=='role_denied' else 'access_denied'),status_code=403 if str(error)=='role_denied' else 401)
            if principal is None and not supplied and operation in settings.get('public_certificate_operations',[]):
                principal={'permissions':['read'],'applications':list(settings['policies'])}
            if principal is None:
                return JSONResponse(envelope(error='access_denied'), status_code=401)
            if permission not in principal['permissions']:
                return JSONResponse(envelope(error='permission_denied'), status_code=403)
            try:
                if request.method == 'GET' or operation=='zkReEncryptRandomKey':
                    payload = dict(request.query_params)
                    payload.update(request.path_params)
                    if operation in {'getCertificate','getAllCertificates'} and 'applicationId' not in payload:
                        raise VaultFailure('applicationId required')
                else:
                    if request.headers.get('content-type', '').split(';')[0] != 'application/json':
                        return JSONResponse(envelope(error='invalid_content_type'), status_code=415)
                    raw = bytearray()
                    async for part in request.stream():
                        raw.extend(part)
                        if len(raw) > (12*1024*1024 if operation=='signPDF' else 256 * 1024):
                            return JSONResponse(envelope(error='request_too_large'), status_code=413)
                    wrapper = json.loads(raw)
                    payload = wrapper.get('request') if isinstance(wrapper, dict) else None
                    if not isinstance(payload, dict):
                        raise VaultFailure('A request object is required')
                if operation in {'uploadCACertificate', 'verifyCertificateTrust','uploadPartnerCertificate'}:
                    if payload.get('partnerDomain') not in principal.get('domains', []):
                        return JSONResponse(envelope(error='scope_denied'), status_code=403)
                elif operation in {'getPartnerCertificate','getPartnerSignedCertificate'}:
                    if not principal.get('domains'):return JSONResponse(envelope(error='scope_denied'),status_code=403)
                elif operation in {'generateLicenseKey','mapLicenseKey','fetchLicenseKeyPermissions'}:
                    if not principal.get('all_tsp_ids') and payload.get('tspId') not in principal.get('tsp_ids',[]):return JSONResponse(envelope(error='scope_denied'),status_code=403)
                elif operation in {'getSigningPublicKey','getEncPublicKey','tpmEncrypt','tpmDecrypt','signData','verifySignature',
                                   'encryptWithPin','decryptWithPin','generateArgon2Hash'}:
                    pass
                elif operation=='generateTokenID':
                    if not principal.get('all_partner_codes') and payload.get('partnercode') not in principal.get('partner_codes',[]):return JSONResponse(envelope(error='scope_denied'),status_code=403)
                elif operation in {'zkEncrypt','zkDecrypt','zkReEncryptRandomKey','getZKTempCertificate','migrateZKKeys'}:
                    if settings['zk_application'] not in principal['applications']:return JSONResponse(envelope(error='scope_denied'),status_code=403)
                else:
                    if operation in {'sign','validate'}:
                        payload.update(applicationId=settings['default_application'],referenceId=settings['default_reference'])
                    if operation in {'jwtSign','jwsSign','jwtVerify'} and not payload.get('applicationId'):
                        payload.update(applicationId=settings['default_application'], referenceId=settings['default_reference'])
                    if payload.get('applicationId') not in principal['applications']:
                        return JSONResponse(envelope(error='scope_denied'), status_code=403)
                    if settings.get('enforce_legacy_signing_scopes') and operation in {'jwtSign','jwsSign','signPDF'}:
                        ref=payload.get('referenceId') or ''
                        if ref and (payload.get('applicationId'),ref)!=(settings['default_application'],settings['default_reference']):
                            return JSONResponse(envelope(error='signing_scope_denied'),status_code=403)
                    if operation == 'jwtVerify' and payload.get('validateTrust') is True and payload.get('domain') not in principal.get('domains', []):
                        return JSONResponse(envelope(error='scope_denied'), status_code=403)
                def dispatch():
                    if operation == 'generateMasterKey':
                        result = engine.generate(payload, request.path_params['objectType'])
                    elif operation == 'generateCSR':
                        result = engine.csr(payload)
                    elif operation == 'getCertificate':
                        result = engine.get(payload['applicationId'], payload.get('referenceId') or '')
                    elif operation == 'getAllCertificates':
                        result = engine.all(payload['applicationId'], payload.get('referenceId') or '')
                    elif operation == 'revokeKey':
                        result = engine.revoke(payload)
                    elif operation == 'uploadCACertificate':
                        result = engine.upload_ca(payload)
                    elif operation == 'verifyCertificateTrust':
                        result = engine.trust(payload)
                    elif operation in {'jwtSign','jwsSign'}:
                        result = jose.sign(engine, payload, jws=operation == 'jwsSign')
                    elif operation == 'jwtVerify':
                        result = jose.verify(engine, payload)
                    elif operation == 'jwtEncrypt':
                        result = jose.encrypt(engine, payload)
                    elif operation == 'jwtDecrypt':
                        result = jose.decrypt(engine, payload)
                    elif operation in {'encryptWithPin','decryptWithPin'}:
                        result=aux.pin(payload,decrypt=operation=='decryptWithPin')
                    elif operation == 'generateArgon2Hash':
                        result=aux.argon(payload)
                    elif operation == 'generateSymmetricKey':
                        result=aux.symmetric(payload)
                    elif operation == 'sign':
                        result=aux.raw_sign(payload)
                    elif operation == 'validate':
                        result=aux.raw_validate(payload)
                    elif operation == 'generateLicenseKey':
                        result=aux.license_generate(payload)
                    elif operation in {'mapLicenseKey','fetchLicenseKeyPermissions'}:
                        result=aux.license_permissions(payload,update=operation=='mapLicenseKey')
                    elif operation == 'uploadPartnerCertificate':
                        result=aux.partner_upload(payload)
                    elif operation in {'getPartnerCertificate','getPartnerSignedCertificate'}:
                        result=aux.partner_get(payload['partnerCertId'],principal['domains'],both=operation=='getPartnerSignedCertificate')
                    elif operation in {'getSigningPublicKey','getEncPublicKey','tpmEncrypt','tpmDecrypt','signData','verifySignature'}:
                        result=client_operation(aux,operation,payload)
                    elif operation in {'encrypt','decrypt'}:
                        result=hybrid(aux,payload,decrypt=operation=='decrypt')
                    elif operation=='generateTokenID':
                        result=token_id(aux,payload)
                    elif operation in {'zkEncrypt','zkDecrypt'}:
                        result=records.attributes(payload,decrypt=operation=='zkDecrypt')
                    elif operation=='zkReEncryptRandomKey':
                        result=records.rewrap(payload)
                    elif operation=='getZKTempCertificate':
                        result=records.temp_certificate()
                    elif operation=='migrateZKKeys':
                        result=records.migrate(payload)
                    elif operation=='migrateBaseKey':
                        result=import_base(aux,payload)
                    elif operation=='signPDF':
                        from native_keymanager_pdf import sign_pdf
                        result=sign_pdf(aux,payload)
                    else:
                        result = engine.upload(payload, verification_only=operation == 'uploadOtherDomainCertificate')
                    return result
                async with slots:
                    result=await run_in_threadpool(dispatch)
                return JSONResponse(envelope(result))
            except (VaultFailure, ValueError, TypeError, KeyError):
                return JSONResponse(envelope(error='invalid_key_request'))
        return invoke

    for name, (method, path, permission) in OPERATIONS.items():
        app.add_api_route(PREFIX+path, endpoint(name), methods=[method], operation_id=name, tags=['key-lifecycle'])

    @app.get('/health', include_in_schema=False)
    @app.get(PREFIX+'/actuator/health', include_in_schema=False)
    def health():
        with engine.vault.connect() as c:owner=c.execute('SELECT owner FROM km_authority WHERE id=1').fetchone()[0]
        return {'status': 'UP', 'owner': owner, 'native_implementation': True,'native_keymanager':True,
                'implemented_operations': len(OPERATIONS), 'production_cutover_verified': owner=='NATIVE' and settings.get('production_acceptance_verified',False),
                'hardware_security_equivalence_claimed': False}
    return app


if os.environ.get('KDBT_NATIVE_KEYMANAGER_SETTINGS'):
    app = build(json.loads(Path(os.environ['KDBT_NATIVE_KEYMANAGER_SETTINGS']).read_text()))
