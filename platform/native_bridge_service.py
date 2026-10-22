"""Standalone authenticated bridge APIs with source-owned standby admission."""
import json,os
from pathlib import Path
import magic
from fastapi import HTTPException
from sqlalchemy import create_engine,text
from starlette.concurrency import run_in_threadpool
from native_bridge_api import create_native_bridge_app
from native_bridge_business import NativeBridgeBusiness
from native_bridge_queries import NativeBridgeQueries
from native_bridge_beneficiary import NativeBridgeBeneficiary
from native_bridge_statements import NativeBridgeStatements
from native_bridge_identity import BridgeIdentityProviders
from native_spar_auth import NativeSparBearer
from native_partner_signatures import NativePartnerSignatures,NativePartnerVerificationKeys,PartnerKeyUnavailable
from native_statement_auth import NativeStatementAuthentication
from native_domain_ownership import NativeDomainOwnership
from registry_native_write_capture import bind_engine


def build(settings):
    if settings['profile'] not in {'partner','beneficiary'}:raise ValueError('Explicit native bridge API profile required')
    engine=create_engine(settings['database_url'],hide_parameters=True,pool_pre_ping=True)
    if settings.get('capture_key'):bind_engine(engine,settings['capture_key'],'native-api')
    ownership=NativeDomainOwnership(engine,'bridge');callback=None
    if settings['profile']=='partner':
        signatures=NativePartnerSignatures(NativePartnerVerificationKeys(settings['native_partner_key_origin']))
        async def authorize(request):
            try:valid=await run_in_threadpool(signatures.verify,request.headers.get('signature',''),await request.json())
            except PartnerKeyUnavailable:raise HTTPException(503,'Registered partner verification keys unavailable') from None
            if not valid:raise HTTPException(401,'Registered partner signature required')
            return 'registered-partner'
        callback=NativeStatementAuthentication(settings['statement_callback_keys'])
    else:
        identities=create_engine(settings['native_identity_database_url'],hide_parameters=True,pool_pre_ping=True);providers=BridgeIdentityProviders(identities,settings['issuer_policy'],cafile=settings['trusted_ca_path']);bearer=NativeSparBearer(providers,allowed_origins=settings['allowed_origins'])
        def authorize(request):return bearer(request)['sub']
    statements=NativeBridgeStatements(engine,max_size=settings['max_upload_file_size'],supported_types=settings['supported_file_types'],detect_mime=lambda body:magic.from_buffer(body,mime=True))
    app=create_native_bridge_app(profile=settings['profile'],business=NativeBridgeBusiness(engine),queries=NativeBridgeQueries(engine),beneficiary=NativeBridgeBeneficiary(engine),statements=statements,authorize=authorize,authorize_callback=callback,writer_admission=ownership.writer)
    @app.get('/health',include_in_schema=False)
    def health():
        with engine.connect() as c:
            owner=c.scalar(text('SELECT owner FROM kdbt_bridge_control.ownership WHERE singleton'));readonly=c.scalar(text('SHOW transaction_read_only'))=='on'
        return {'ready':True,'profile':settings['profile'],'owner':owner,'database_read_only':readonly,'business_writes_enabled':owner=='NATIVE' and not readonly,'authentication_configured':True,'signed_statement_callbacks_configured':callback is not None,'legacy_business_http_dependency':False}
    return app


if os.environ.get('KDBT_NATIVE_BRIDGE_SETTINGS'):app=build(json.loads(Path(os.environ['KDBT_NATIVE_BRIDGE_SETTINGS']).read_text()))
