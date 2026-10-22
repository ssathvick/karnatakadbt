"""Strict Keycloak JWT adapter. No unsigned-token or development fallback."""
from urllib.parse import urlsplit
import jwt
from fastapi import HTTPException
from approval_policy_api import ApprovalIdentity


class ApprovalTokenVerifier:
    def __init__(self, issuers, audience, jwks_url, key_lookup=None):
        if not issuers or not audience or any(not value for value in issuers):
            raise ValueError('Explicit approval issuers and audience are required')
        url = urlsplit(jwks_url)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError('A trusted HTTPS JWKS endpoint is required')
        self.issuers, self.audience = tuple(issuers), audience
        self.key_lookup = key_lookup or jwt.PyJWKClient(jwks_url, timeout=5).get_signing_key_from_jwt

    def __call__(self, token):
        try:
            key = self.key_lookup(token)
            claims = jwt.decode(token, getattr(key, 'key', key), algorithms=['RS256'],
                issuer=self.issuers, audience=self.audience,
                options={'require': ['sub', 'iss', 'aud', 'exp', 'iat']})
            subject = claims['sub']
            if not isinstance(subject, str) or not subject or len(subject) > 128:
                raise ValueError('Invalid subject')
            roles = set((claims.get('realm_access') or {}).get('roles') or [])
            for entry in (claims.get('resource_access') or {}).values():
                if isinstance(entry, dict):
                    roles.update(entry.get('roles') or [])
            assignee = next((str(claims[field]).strip() for field in
                             ['preferred_username', 'username', 'sub'] if claims.get(field) and str(claims[field]).strip()), subject)
            name = str(claims.get('name') or '').strip() or None
            return ApprovalIdentity(subject, frozenset(roles), claims.get('email'), assignee, name)
        except jwt.PyJWKClientConnectionError:
            raise HTTPException(503, 'Approval identity provider unavailable') from None
        except Exception:
            raise HTTPException(401, 'Invalid bearer token') from None
