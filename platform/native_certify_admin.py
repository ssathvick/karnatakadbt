"""Credential administration bound to the existing portal client role."""
import ssl

import jwt


class CertifyAdministrator:
    CLIENT = 'register-staff-portal'
    ROLE = 'Technical Administrator'

    def __init__(self, settings, key_lookup=None):
        if settings.get('issuer') != 'https://localhost:8444/realms/staff':
            raise ValueError('Existing staff issuer required')
        if not settings.get('audiences'):
            raise ValueError('Explicit audience required')
        self.settings = settings
        self.lookup = key_lookup or jwt.PyJWKClient(
            settings['jwks_url'], timeout=5,
            ssl_context=ssl.create_default_context(cafile=settings.get('ca_file'))
        ).get_signing_key_from_jwt

    def authorize(self, token):
        if not isinstance(token, str) or not token or len(token) > 16384:
            return False
        try:
            key = self.lookup(token)
            claims = jwt.decode(token, getattr(key, 'key', key), algorithms=['RS256'],
                                issuer=self.settings['issuer'], audience=self.settings['audiences'],
                                options={'require': ['exp', 'iat', 'iss', 'aud', 'sub']})
            roles = claims.get('resource_access', {}).get(self.CLIENT, {}).get('roles', [])
            return bool(isinstance(claims['sub'], str) and claims['sub'] and
                        isinstance(roles, list) and all(isinstance(r, str) for r in roles) and
                        self.ROLE in roles)
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, AttributeError, OSError):
            return False
