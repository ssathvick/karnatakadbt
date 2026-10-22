"""Reload committed provider configuration without restarting OAuth sessions.

Identity roots come only from the privileged SQL catalogue. Unchanged rows reuse
discovery/JWK clients; changed rows must pass trusted HTTPS discovery afresh.
Removed/inactive providers disappear immediately, with no stale fallback.
"""
import hashlib,json,threading,time,logging
from urllib.parse import urlsplit
import httpx,jwt
from sqlalchemy import select
from native_oidc import NativeOIDC

class DatabaseOidcProviders:
    def __init__(self,engine,table,*,verify,default_redirect_uri,transport=None,key_factory=None):
        self.engine,self.table,self.verify=engine,table,verify;self.default_redirect_uri=default_redirect_uri;self.transport=transport;self.key_factory=key_factory;self.lock=threading.Lock();self.cache={}
    @staticmethod
    def https(value):
        url=urlsplit(value)
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.fragment:raise ValueError('Configured HTTPS provider endpoint required')
        return value
    def __call__(self):
        with self.engine.connect() as c:rows=[dict(row) for row in c.execute(select(self.table).where(self.table.c.active.is_(True))).mappings()]
        with self.lock:
            result={};cache={}
            for row in rows:
                digest=hashlib.sha256(json.dumps(row,sort_keys=True,default=str).encode()).hexdigest();identifier=str(row['id']);prior=self.cache.get(identifier)
                if prior and prior[0]==digest and (prior[1] is not None or time.monotonic()<prior[2]):
                    if prior[1] is not None:result[identifier]=prior[1]
                    cache[identifier]=prior;continue
                try:provider=self.resolve(row)
                except Exception:
                    # An unavailable new provider must neither retain stale
                    # credentials nor disable existing unrelated providers.
                    logging.getLogger('karnatakadbt.oauth').warning('Configured login provider is unavailable')
                    cache[identifier]=(digest,None,time.monotonic()+30);continue
                result[identifier]=provider;cache[identifier]=(digest,provider,0)
            self.cache=cache;return result
    def resolve(self,row):
        issuer=self.https(row['issuer']);metadata_url=self.https(row.get('server_metadata_url') or issuer.rstrip('/')+'/.well-known/openid-configuration')
        with httpx.Client(verify=self.verify,trust_env=False,timeout=20,transport=self.transport,follow_redirects=False) as client:
            response=client.get(metadata_url);response.raise_for_status();metadata=response.json()
        if metadata['issuer']!=issuer:raise ValueError('Configured provider issuer differs from discovery')
        jwks=self.https(row.get('jwks_uri') or metadata['jwks_uri']);keys=self.key_factory(jwks) if self.key_factory else jwt.PyJWKClient(jwks,ssl_context=self.verify)
        provider={'issuer':issuer,'authorization_endpoint':self.https(row.get('authorization_endpoint') or metadata['authorization_endpoint']),'token_endpoint':self.https(row.get('token_endpoint') or metadata['token_endpoint']),'callback_uri':self.https(row['oauth_callback_url']),'client_id':row['client_id'],'client_secret':row.get('client_secret'),'client_private_key':row.get('client_private_key'),'jwt_assertion_aud':row.get('jwt_assertion_aud'),'auth_method':row['token_endpoint_auth_method'],'access_audience':'account','algorithms':['RS256'],'key_lookup':lambda kid,keys=keys:keys.get_signing_key(kid).key,'scope':row.get('scope') or 'openid profile email','default_redirect_uri':row.get('default_redirect_uri') or self.default_redirect_uri}
        for field in ['userinfo_endpoint','end_session_endpoint']:
            value=row.get(field) or metadata.get(field)
            if value:provider[field]=self.https(value)
        NativeOIDC._validate({'configured':provider})
        return provider
