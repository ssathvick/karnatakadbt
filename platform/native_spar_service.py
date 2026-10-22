"""Standalone native mapping runtime; original business services are not used."""
import json,os,ssl,threading
from pathlib import Path
from urllib.parse import urlsplit
import httpx,jwt
from sqlalchemy import create_engine,text
from native_partner_signatures import NativePartnerSignatures,NativePartnerVerificationKeys
from native_spar_api import create_native_spar_app
from native_spar_auth import NativeSparBearer
from native_spar_ownership import NativeSparOwnership
from native_spar_store import NativeSparStore
from registry_native_write_capture import bind_engine


class MappingIdentityProviders:
    """Only configured active identity rows can authorize a mapping request."""
    def __init__(self,engine,issuer_policy,*,cafile):
        self.engine,self.policy=engine,issuer_policy;self.context=ssl.create_default_context(cafile=cafile);self.cache={};self.lock=threading.Lock()
    @staticmethod
    def https(value):
        parsed=urlsplit(value)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:raise ValueError('Trusted HTTPS identity endpoint required')
        return value
    def __call__(self):
        with self.engine.connect() as c:
            rows=[dict(row) for row in c.execute(text('SELECT issuer,jwks_uri,server_metadata_url FROM public.login_providers WHERE active=true')).mappings()]
        result={}
        with self.lock:
            for row in rows:
                issuer=row['issuer'];policy=self.policy.get(issuer)
                if not policy:continue
                self.https(issuer);key=(issuer,row.get('jwks_uri'),row.get('server_metadata_url'))
                if key not in self.cache:
                    url=row.get('jwks_uri')
                    if not url:
                        with httpx.Client(verify=self.context,trust_env=False,follow_redirects=False,timeout=10) as client:
                            response=client.get(self.https(row.get('server_metadata_url') or issuer.rstrip('/')+'/.well-known/openid-configuration'));response.raise_for_status();metadata=response.json()
                        if metadata['issuer']!=issuer:raise ValueError('Mapping identity discovery issuer mismatch')
                        url=metadata['jwks_uri']
                    self.cache[key]=jwt.PyJWKClient(self.https(url),ssl_context=self.context,timeout=10)
                client=self.cache[key]
                result[issuer]=dict(policy,issuer=issuer,algorithms=['RS256'],key_lookup=lambda kid,client=client:client.get_signing_key(kid).key)
            self.cache={key:value for key,value in self.cache.items() if key[0] in result}
        return result


def build(settings):
    engine=create_engine(settings['database_url'],hide_parameters=True,pool_pre_ping=True)
    if settings.get('capture_key'):bind_engine(engine,settings['capture_key'],'native-api')
    store=NativeSparStore(engine);ownership=NativeSparOwnership(engine)
    signatures=authenticate=None
    if settings['profile']=='partner':
        signatures=NativePartnerSignatures(NativePartnerVerificationKeys(settings['native_partner_key_origin']))
    else:
        identities=create_engine(settings['native_identity_database_url'],hide_parameters=True,pool_pre_ping=True)
        providers=MappingIdentityProviders(identities,settings['issuer_policy'],cafile=settings['trusted_ca_path'])
        authenticate=NativeSparBearer(providers,allowed_origins=settings['allowed_origins'])
    app=create_native_spar_app(store,profile=settings['profile'],signatures=signatures,authenticate=authenticate,writer_admission=ownership.writer)
    @app.get('/health',include_in_schema=False)
    def health():
        with engine.connect() as c:owner=c.execute(text('SELECT owner FROM kdbt_spar_control.ownership WHERE singleton')).scalar_one()
        return {'ready':True,'profile':settings['profile'],'ownership':owner,'business_writes_enabled':owner=='NATIVE','legacy_business_http_dependency':False}
    return app

if os.environ.get('KDBT_NATIVE_SPAR_SETTINGS'):
    app=build(json.loads(Path(os.environ['KDBT_NATIVE_SPAR_SETTINGS']).read_text()))
