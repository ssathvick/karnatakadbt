"""Native authorization-code/PKCE, refresh and back-channel logout engine.

Upstream Keycloak remains the identity provider. Endpoint/key material comes
from trusted deployment configuration, never from token-controlled URLs.
HTTP controllers and cookie compatibility must be accepted before live routing.
"""
import base64
import hashlib
import hmac
import time
import logging
import secrets
from urllib.parse import urlencode, urlsplit

import httpx
import jwt


class OAuthRejected(Exception):
    def __init__(self):
        super().__init__('Authentication rejected')


class NativeOIDC:
    def __init__(self, sessions, providers, *, redirect_origins, transport=None, verify=True,provider_loader=None):
        self.sessions, self._providers = sessions, dict(providers)
        self.provider_loader=provider_loader
        self.redirect_origins = frozenset(redirect_origins)
        self.transport, self.verify = transport, verify
        self._validate(self._providers)

    @staticmethod
    def _validate(providers):
        for provider in providers.values():
            if provider['auth_method'] not in {'client_secret_basic', 'client_secret_post', 'private_key_jwt','none'}:
                raise ValueError('Unsupported configured OIDC client authentication')
            if provider['auth_method']=='private_key_jwt' and not provider.get('client_private_key'):raise ValueError('Configured private client key required')
            for name in ['issuer', 'authorization_endpoint', 'token_endpoint', 'callback_uri']:
                parsed = urlsplit(provider[name])
                if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
                    raise ValueError('Trusted HTTPS OIDC endpoint required')
            if not set(provider['algorithms']).issubset({'RS256', 'ES256', 'EdDSA'}) or not provider['algorithms']:
                raise ValueError('Asymmetric identity algorithms required')

    @property
    def providers(self):
        if self.provider_loader is None:return self._providers
        try:
            providers=dict(self.provider_loader());self._validate(providers);return providers
        except Exception:raise OAuthRejected() from None

    def _provider(self, provider_id):
        provider = self.providers.get(str(provider_id))
        if not provider or not provider.get('active', True):
            raise OAuthRejected()
        return provider

    def _redirect(self, target):
        if not isinstance(target, str) or any(ord(c) < 32 or c == '\\' for c in target):
            raise OAuthRejected()
        parsed = urlsplit(target)
        if parsed.username or parsed.password or parsed.fragment:
            raise OAuthRejected()
        if target.startswith('/') and not target.startswith('//') and not parsed.netloc:
            return target
        if parsed.scheme == 'https' and parsed.scheme + '://' + parsed.netloc in self.redirect_origins:
            return target
        raise OAuthRejected()

    def start(self, provider_id, redirect_uri='/', *, browser_binding=None):
        provider = self._provider(provider_id)
        target = self._redirect(redirect_uri)
        context={'browser_binding':hashlib.sha256(browser_binding.encode()).hexdigest()} if browser_binding else None
        transaction = self.sessions.create_transaction(str(provider_id), target, context=context)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(transaction['code_verifier'].encode()).digest()).rstrip(b'=').decode()
        params = dict(response_type='code', client_id=provider['client_id'], redirect_uri=provider['callback_uri'],
                      scope=provider.get('scope', 'openid profile email'), state=transaction['state'],
                      nonce=transaction['nonce'], code_challenge=challenge, code_challenge_method='S256')
        separator = '&' if '?' in provider['authorization_endpoint'] else '?'
        return {'redirectUrl': provider['authorization_endpoint'] + separator + urlencode(params), 'state': transaction['state']}

    def _claims(self, token, provider, *, audience, required, require_subject=True):
        try:
            header = jwt.get_unverified_header(token)
            if header.get('crit') or header.get('alg') not in provider['algorithms']:
                raise OAuthRejected()
            key = provider['key_lookup'](header.get('kid'))
            if key is None:
                raise OAuthRejected()
            claims = jwt.decode(token, key, algorithms=provider['algorithms'], issuer=provider['issuer'],
                                audience=audience, options={'require': required}, leeway=0)
            if require_subject and (not isinstance(claims.get('sub'), str) or not claims['sub']):
                raise OAuthRejected()
            return claims
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            raise OAuthRejected() from None

    def _tokens(self, response, provider, *, nonce=None, previous=None):
        if not isinstance(response, dict) or not response.get('access_token'):
            raise OAuthRejected()
        access = self._claims(response['access_token'], provider, audience=provider['access_audience'],
                              required=['iss', 'sub', 'aud', 'exp', 'iat', 'sid'])
        if not isinstance(access['sid'], str) or not access['sid']:
            raise OAuthRejected()
        if response.get('id_token'):
            identity = self._claims(response['id_token'], provider, audience=provider['client_id'],
                                    required=['iss', 'sub', 'aud', 'exp', 'iat'])
            if identity['sub'] != access['sub'] or (identity.get('sid') and identity['sid'] != access['sid']):
                raise OAuthRejected()
            audiences = identity['aud'] if isinstance(identity['aud'], list) else [identity['aud']]
            if (len(audiences) > 1 or identity.get('azp')) and identity.get('azp') != provider['client_id']:
                raise OAuthRejected()
            if nonce is not None and (not isinstance(identity.get('nonce'), str) or not hmac.compare_digest(identity['nonce'], nonce)):
                raise OAuthRejected()
            if identity.get('at_hash'):
                digest=hashlib.sha256(response['access_token'].encode()).digest()
                expected=base64.urlsafe_b64encode(digest[:len(digest)//2]).rstrip(b'=').decode()
                if not isinstance(identity['at_hash'],str) or not hmac.compare_digest(identity['at_hash'],expected):
                    raise OAuthRejected()
        elif nonce is not None:
            raise OAuthRejected()
        if previous and (access['sid'] != previous['session_id'] or access['iss'] != previous['issuer']):
            raise OAuthRejected()
        return access

    async def _exchange(self, provider, data):
        auth = None
        if provider['auth_method'] == 'client_secret_basic':
            auth = (provider['client_id'], provider['client_secret'])
        else:
            data['client_id'] = provider['client_id']
            if provider['auth_method'] == 'client_secret_post':
                data['client_secret'] = provider['client_secret']
            elif provider['auth_method']=='private_key_jwt':
                try:
                    from cryptography.hazmat.primitives.serialization import load_pem_private_key
                    from cryptography.hazmat.primitives.asymmetric import rsa,ec,ed25519
                    pem=provider['client_private_key'];key=load_pem_private_key(pem.encode() if isinstance(pem,str) else pem,password=None)
                    algorithm='RS256' if isinstance(key,rsa.RSAPrivateKey) and key.key_size>=2048 else 'ES256' if isinstance(key,ec.EllipticCurvePrivateKey) and key.curve.name=='secp256r1' else 'EdDSA' if isinstance(key,ed25519.Ed25519PrivateKey) else None
                    if algorithm is None:raise ValueError('Unsupported private client key')
                    now=int(time.time());claims={'iss':provider['client_id'],'sub':provider['client_id'],'aud':provider.get('jwt_assertion_aud') or provider['token_endpoint'],'iat':now,'exp':now+60,'jti':secrets.token_urlsafe(32)}
                    data['client_assertion_type']='urn:ietf:params:oauth:client-assertion-type:jwt-bearer';data['client_assertion']=jwt.encode(claims,key,algorithm=algorithm)
                except Exception:raise OAuthRejected() from None
        try:
            async with httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False,
                                         transport=self.transport, verify=self.verify) as client:
                response = await client.post(provider['token_endpoint'], data=data, auth=auth)
                if response.status_code != 200:
                    raise OAuthRejected()
                return response.json()
        except (httpx.HTTPError, ValueError):
            raise OAuthRejected() from None

    async def complete(self, state, code, *, browser_binding=None):
        transaction = self.sessions.consume_transaction(state)
        if not transaction or not isinstance(code, str) or not code:
            raise OAuthRejected()
        binding=(transaction.get('context') or {}).get('browser_binding')
        if binding and (not browser_binding or not hmac.compare_digest(binding,hashlib.sha256(browser_binding.encode()).hexdigest())):
            raise OAuthRejected()
        provider = self._provider(transaction['login_provider_id'])
        response = await self._exchange(provider, dict(grant_type='authorization_code', code=code,
                         code_verifier=transaction['code_verifier'], redirect_uri=provider['callback_uri']))
        claims = self._tokens(response, provider, nonce=transaction['nonce'])
        self.sessions.create_session(claims['sid'], response, provider['issuer'])
        return {'redirect_uri': self._redirect(transaction['redirect_uri']), 'token_response': response, 'session_id': claims['sid']}

    async def refresh(self, session_id):
        previous = self.sessions.read_session(session_id)
        if not previous:
            raise OAuthRejected()
        providers = [p for p in self.providers.values() if p['issuer'] == previous['issuer'] and p.get('active', True)]
        if len(providers) != 1:
            raise OAuthRejected()
        provider = providers[0]
        response = await self._exchange(provider, dict(grant_type='refresh_token', refresh_token=previous['refresh_token']))
        self._tokens(response, provider, previous=previous)
        if not self.sessions.rotate_session(previous, response):
            raise OAuthRejected()
        return response

    def backchannel_logout(self, token):
        stage='token_parse'
        try:
            issuer = jwt.decode(token, options={'verify_signature': False}).get('iss')
            providers = [p for p in self.providers.values() if p['issuer'] == issuer and p.get('active', True)]
            if len(providers) != 1:
                raise OAuthRejected()
            provider = providers[0]
            stage='signed_claims'
            claims = self._claims(token, provider, audience=provider['client_id'], required=['iss', 'aud', 'iat', 'jti'], require_subject=False)
            stage='logout_event'
            if ('nonce' in claims or abs(time.time() - claims['iat']) > 300 or not claims.get('sid') or
                    claims.get('events', {}).get('http://schemas.openid.net/event/backchannel-logout') != {}):
                raise OAuthRejected()
            replay = hashlib.sha256((issuer + ':' + claims['jti']).encode()).hexdigest()
            stage='replay'
            if not self.sessions.redis.set('native_logout_seen:' + replay, '1', ex=600, nx=True):
                raise OAuthRejected()
            self.sessions.delete_session(claims['sid'])
        except OAuthRejected:
            logging.getLogger('karnatakadbt.oauth').warning('Native back-channel logout rejected at %s',stage)
            raise
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            logging.getLogger('karnatakadbt.oauth').warning('Native back-channel logout rejected at %s',stage)
            raise OAuthRejected() from None
