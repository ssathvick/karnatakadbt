"""Configured consent trust, persistent signing and native partner key lookup."""
import json,ssl
from pathlib import Path
import jwt
from cryptography.hazmat.primitives import serialization
from sqlalchemy import create_engine
from native_consent_lifecycle import NativeConsentLifecycle
from native_consent_receipts import NativeConsentReceipts
from native_consent_verification import NativeConsentVerification
from native_consent_public_api import NativeConsentBearer,create_native_consent_public_api
from native_partner_engine import NativePartnerEngine
from consent_subject_console import mount_subject_console


class ConsentSubjectIdentity:
    def __init__(self,providers,*,default_subject_type,key_clients=None):
        if not providers or not default_subject_type:raise ValueError('Subject identity trust must be explicit')
        self.providers=providers;self.default_type=default_subject_type;self.clients=key_clients or {}
        for issuer,config in providers.items():
            if not config.get('audiences') or not config.get('jwks_uri'):raise ValueError('Subject issuer keys and audience required')
    def __call__(self,token):
        try:
            claims=jwt.decode(token,options={'verify_signature':False});issuer=claims.get('iss');config=self.providers.get(issuer)
            if not config:raise ValueError('Untrusted subject issuer')
            client=self.clients[issuer]
            header=jwt.get_unverified_header(token)
            if header.get('alg') not in {'RS256','ES256','EdDSA'} or header.get('crit'):raise ValueError('Invalid subject signing algorithm')
            key=client.get_signing_key_from_jwt(token).key
            claims=jwt.decode(token,key,algorithms=['RS256','ES256','EdDSA'],issuer=issuer,audience=config['audiences'],options={'require':['iss','sub','aud','exp','iat']})
            claims['subject_id_type']=claims.get('subject_id_type') or self.default_type
            return claims
        except Exception:raise ValueError('Subject identity rejected') from None


def build_native_consent_public(settings,*,key_client_factory=None,consent_engine=None):
    key_path=Path(settings['signing_key_path'])
    if key_path.stat().st_mode&0o077:raise ValueError('Signing key must be private')
    key=serialization.load_pem_private_key(key_path.read_bytes(),password=None)
    receipts=NativeConsentReceipts(key,settings['signing_kid'])
    context=ssl.create_default_context(cafile=settings['trusted_ca_path'])
    providers={issuer:{**value,'audiences':list(value['audiences'])} for issuer,value in settings['subject_providers'].items()}
    caller=settings['caller_identity']
    # Original browser consent authenticates with its access token. The caller
    # issuer/audience is already explicitly trusted by the public API.
    if caller['issuer'] in providers and caller['audience'] not in providers[caller['issuer']]['audiences']:providers[caller['issuer']]['audiences'].append(caller['audience'])
    make_client=key_client_factory or (lambda uri:jwt.PyJWKClient(uri,ssl_context=context))
    clients={issuer:make_client(value['jwks_uri']) for issuer,value in providers.items()}
    subject=ConsentSubjectIdentity(providers,default_subject_type=settings['subject_default_id_type'],key_clients=clients)
    engine=consent_engine if consent_engine is not None else create_engine(settings['consent_database_url'],hide_parameters=True)
    partner_engine=create_engine(settings['partner_database_url'],hide_parameters=True);partners=NativePartnerEngine(partner_engine)
    def partner_key(reference,kid,algorithm):
        rows=[row for row in partners.servable_keys(reference) if row['kid']==kid and row['algorithm']==algorithm]
        if len(rows)!=1:raise ValueError('Partner key not active or ambiguous')
        return serialization.load_pem_public_key(rows[0]['public_key'].encode())
    lifecycle=NativeConsentLifecycle(engine,verify_identity=subject,receipt_builder=receipts.build)
    verifier=NativeConsentVerification(lifecycle,partner_key=partner_key,freshness_seconds=settings['freshness_seconds'])
    caller=settings['caller_identity'];caller_client=make_client(caller['jwks_uri'])
    admission=NativeConsentBearer(issuer=caller['issuer'],audience=caller['audience'],key_lookup=lambda kid:caller_client.get_signing_key(kid).key,default_subject_type=settings['subject_default_id_type'])
    app=create_native_consent_public_api(lifecycle,verifier,receipts,authenticate=admission)
    mount_subject_console(app,settings.get('subject_ui',{'issuer':'https://localhost:8444/realms/staff','client_id':'consent-manager-ui','redirect_uri':'https://localhost:8449/subject/'}))
    app.state.native_consent_store=lifecycle;app.state.native_consent_receipts=receipts;app.state.native_partner_engine=partners
    app.state.production_signing_identity_is_demo=False
    app.state.legacy_business_http_calls=0
    return app
