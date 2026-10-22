"""Native OIDC transport and claim validation; no registry framework imports."""
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode, urlsplit, parse_qsl, urlunsplit

import httpx
import jwt


class IdentityFailure(ValueError):
    """A safe, non-identifying reason suitable for the authentication history."""


class BeneficiaryOIDC:
    ALGORITHMS = ('RS256', 'RS384', 'RS512', 'ES256', 'ES384', 'ES512', 'EdDSA')
    ADAPTERS = {'default_oidc', 'keycloak', 'esignet'}

    def __init__(self, transport=None, assertion_signer=None):
        self.transport = transport
        self.assertion_signer = assertion_signer

    @staticmethod
    def url(value):
        parsed = urlsplit(value or '')
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise IdentityFailure('Authentication provider endpoint is misconfigured.')
        return value

    def request(self, method, url, **kwargs):
        self.url(url)
        try:
            with httpx.Client(timeout=15, trust_env=False, follow_redirects=False, transport=self.transport) as client:
                response = client.request(method, url, **kwargs)
                response.raise_for_status()
                if len(response.content) > 1048576:
                    raise IdentityFailure('Authentication provider response is too large.')
                return response
        except IdentityFailure:
            raise
        except Exception:
            raise IdentityFailure('Authentication provider request failed.') from None

    def metadata(self, provider):
        if provider.get('adapter_name') not in self.ADAPTERS:
            raise IdentityFailure('Authentication provider adapter is unsupported.')
        extra = provider.get('provider_config') or {}
        metadata_url = provider.get('server_metadata_url')
        issuer = extra.get('issuer')
        if not metadata_url and issuer:
            metadata_url = issuer.rstrip('/') + '/.well-known/openid-configuration'
        metadata = self.request('GET', metadata_url).json() if metadata_url else {}
        if not isinstance(metadata, dict):
            raise IdentityFailure('Authentication provider metadata is invalid.')
        for source, target in [('authorization_endpoint', 'authorization_endpoint'), ('token_endpoint', 'token_endpoint'),
                               ('userinfo_endpoint', 'userinfo_endpoint'), ('jwks_endpoint', 'jwks_uri')]:
            if provider.get(source):
                metadata[target] = provider[source]
        if issuer:
            if metadata.get('issuer') and metadata['issuer'] != issuer:
                raise IdentityFailure('Authentication provider issuer does not match configuration.')
            metadata['issuer'] = issuer
        for field in ['authorization_endpoint', 'token_endpoint', 'jwks_uri', 'issuer']:
            self.url(metadata.get(field))
        self.url(provider.get('oauth_callback_url'))
        if not provider.get('client_id'):
            raise IdentityFailure('Authentication provider client is misconfigured.')
        return metadata

    def authorization(self, provider, state, nonce, verifier, metadata):
        extra = (provider.get('provider_config') or {}).get('extra_authorize_params') or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except (TypeError, ValueError):
                extra = {}
        if not isinstance(extra, dict):
            extra = {}
        extra = dict(extra)
        if provider['adapter_name'] == 'esignet' and isinstance(extra.get('claims'), (list, dict)):
            extra['claims'] = json.dumps(extra['claims'], separators=(',', ':'))
        # Security parameters cannot be replaced by configuration extras.
        params = {**extra, 'client_id': provider['client_id'], 'redirect_uri': provider['oauth_callback_url'],
                  'scope': (provider.get('provider_config') or {}).get('scope') or 'openid profile',
                  'state': state, 'nonce': nonce, 'response_type': 'code',
                  'code_challenge': base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode(),
                  'code_challenge_method': 'S256'}
        parsed = urlsplit(metadata['authorization_endpoint'])
        original = {key: value for key, value in parse_qsl(parsed.query) if key not in params}
        return urlunsplit(parsed._replace(query=urlencode({**original, **params})))

    def exchange(self, provider, code, transaction, metadata):
        form = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': provider['oauth_callback_url'],
                'code_verifier': transaction['verifier'], 'client_id': provider['client_id']}
        method = provider.get('token_endpoint_auth_method') or 'client_secret_basic'
        kwargs = {}
        if method == 'client_secret_basic':
            # RFC 6749 requires form-escaping each Basic credential component.
            from urllib.parse import quote_plus
            kwargs['auth'] = (quote_plus(provider['client_id']), quote_plus(provider.get('client_secret') or ''))
        elif method == 'client_secret_post':
            form['client_secret'] = provider.get('client_secret') or ''
        elif method in {'private_key_jwt', 'private_key_jwt_keymanager'}:
            now = int(time.time())
            claims = {'iss': provider['client_id'], 'sub': provider['client_id'], 'aud': metadata['token_endpoint'],
                      'iat': now, 'exp': now + 300, 'jti': secrets.token_urlsafe(24)}
            if method == 'private_key_jwt':
                try:
                    assertion = jwt.encode(claims, provider['client_private_key'], algorithm='RS256')
                except Exception:
                    raise IdentityFailure('Authentication provider signing key is unavailable.') from None
            else:
                if self.assertion_signer is None:
                    raise IdentityFailure('Authentication provider key manager is unavailable.')
                assertion = self.assertion_signer(claims, provider)
            form.update(client_assertion_type='urn:ietf:params:oauth:client-assertion-type:jwt-bearer', client_assertion=assertion)
        elif method != 'none':
            raise IdentityFailure('Authentication provider token method is unsupported.')
        result = self.request('POST', metadata['token_endpoint'], data=form, **kwargs).json()
        if not isinstance(result, dict) or not result.get('id_token'):
            raise IdentityFailure('Missing id_token in token response.')
        return result

    def decode(self, provider, token, nonce, metadata, access_token=None):
        try:
            header = jwt.get_unverified_header(token)
            algorithm = header.get('alg')
            if algorithm not in self.ALGORITHMS:
                raise ValueError()
            jwks = self.request('GET', metadata['jwks_uri']).json()
            keys = [key for key in jwks['keys'] if key.get('use', 'sig') == 'sig'
                    and (not key.get('alg') or key['alg'] == algorithm)
                    and ('kid' not in header or key.get('kid') == header['kid'])]
            if len(keys) != 1:
                raise ValueError()
            key = jwt.PyJWK.from_dict(keys[0], algorithm=algorithm).key
            audiences = (provider.get('provider_config') or {}).get('audiences') or [provider['client_id']]
            required = ['exp', 'iat', 'iss', 'aud', 'sub', 'nonce'] if nonce is not None else ['iss', 'aud', 'sub']
            claims = jwt.decode(token, key, algorithms=[algorithm], issuer=metadata['issuer'], audience=audiences,
                                options={'require': required})
            if nonce is not None and not hmac.compare_digest(str(claims['nonce']), nonce):
                raise ValueError()
            aud = claims['aud']
            if (isinstance(aud, list) and len(aud) > 1 or 'azp' in claims) and claims.get('azp') != provider['client_id']:
                raise ValueError()
            if nonce is not None and claims.get('at_hash'):
                if not access_token:
                    raise ValueError()
                hash_name = 'sha' + algorithm[-3:] if algorithm != 'EdDSA' else 'sha512'
                digest = hashlib.new(hash_name, access_token.encode()).digest()
                expected = base64.urlsafe_b64encode(digest[:len(digest)//2]).rstrip(b'=').decode()
                if not hmac.compare_digest(expected, claims['at_hash']):
                    raise ValueError()
            return claims
        except IdentityFailure:
            raise
        except Exception:
            raise IdentityFailure('Identity token signature or claims are invalid.') from None

    def complete(self, provider, code, transaction):
        metadata = transaction['metadata']
        tokens = self.exchange(provider, code, transaction, metadata)
        claims = self.decode(provider, tokens['id_token'], transaction['nonce'], metadata, tokens.get('access_token'))
        adapter = provider['adapter_name']
        if adapter == 'esignet' and tokens.get('access_token') and metadata.get('userinfo_endpoint'):
            # Optional enrichment can fail, as in the retained adapter. Identity
            # fields are accepted only from verified, subject-bound userinfo.
            try:
                response = self.request('GET', metadata['userinfo_endpoint'], headers={'Authorization': 'Bearer ' + tokens['access_token']})
                userinfo = (self.decode(provider, response.text, None, metadata, tokens['access_token'])
                            if response.headers.get('content-type', '').startswith('application/jwt') else response.json())
                if not isinstance(userinfo, dict) or userinfo.get('sub') != claims['sub']:
                    raise IdentityFailure('User information subject does not match the identity token.')
                claims.update({key: value for key, value in userinfo.items() if key not in {'iss', 'aud', 'exp', 'iat', 'nonce', 'azp', 'at_hash'}})
            except IdentityFailure as error:
                if str(error) == 'User information subject does not match the identity token.':
                    raise
        if adapter in {'keycloak', 'esignet'} and 'roles' not in claims:
            realm = (claims.get('realm_access') or {}).get('roles') or []
            roles = set(realm)
            if adapter == 'keycloak':
                for item in (claims.get('resource_access') or {}).values():
                    roles.update((item or {}).get('roles') or [])
            if roles:
                claims['roles'] = sorted(roles) if adapter == 'keycloak' else realm
        subject = claims.get('individual_id') or claims.get('sub') if adapter == 'esignet' else claims.get('sub')
        return tokens, claims, str(subject) if subject is not None else None


def authentication_details(claims):
    amr = claims.get('amr')
    method = amr[0] if isinstance(amr, list) and amr and isinstance(amr[0], str) and amr[0] else None
    acr = claims.get('acr')
    if not method and isinstance(acr, str) and acr:
        method = next((item for item in ['otp', 'biometric', 'face', 'fingerprint', 'password'] if item in acr.lower()), acr)
    verified = {}
    for source, target in [('email_verified', 'email_verified'), ('phone_number_verified', 'phone_verified')]:
        if source in claims:
            verified[target] = bool(claims[source])
    if isinstance(claims.get('verified_attributes'), list):
        verified.update({item: True for item in claims['verified_attributes'] if isinstance(item, str) and item})
    return method, verified or None
