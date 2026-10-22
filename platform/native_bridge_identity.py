"""Resolve only active, operator-approved identity providers from native IAM."""
import ssl,threading
from urllib.parse import urlsplit
import httpx,jwt
from sqlalchemy import text


class BridgeIdentityProviders:
    def __init__(self,engine,policy,*,cafile):
        self.engine,self.policy=engine,dict(policy);self.ssl=ssl.create_default_context(cafile=cafile);self.clients={};self.lock=threading.Lock()
    @staticmethod
    def https(value):
        parsed=urlsplit(value or '')
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:raise ValueError('Approved HTTPS identity endpoint required')
        return value
    def __call__(self):
        with self.engine.connect() as c:rows=c.execute(text('SELECT issuer,jwks_uri,server_metadata_url FROM public.login_providers WHERE active=true')).mappings().all()
        result={}
        with self.lock:
            for row in rows:
                issuer=row['issuer'];policy=self.policy.get(issuer)
                if not policy:continue
                self.https(issuer);identity=(issuer,row['jwks_uri'],row['server_metadata_url'])
                if identity not in self.clients:
                    url=row['jwks_uri']
                    if not url:
                        with httpx.Client(verify=self.ssl,trust_env=False,follow_redirects=False,timeout=10) as http:
                            response=http.get(self.https(row['server_metadata_url'] or issuer.rstrip('/')+'/.well-known/openid-configuration'));response.raise_for_status();metadata=response.json()
                        if metadata['issuer']!=issuer:raise ValueError('Identity issuer mismatch')
                        url=metadata['jwks_uri']
                    self.clients[identity]=jwt.PyJWKClient(self.https(url),ssl_context=self.ssl,timeout=10)
                client=self.clients[identity];result[issuer]=dict(policy,issuer=issuer,algorithms=['RS256'],key_lookup=lambda kid,client=client:client.get_signing_key(kid).key)
            self.clients={key:value for key,value in self.clients.items() if key[0] in result}
        return result
