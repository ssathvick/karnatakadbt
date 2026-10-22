"""Verify mapping identities against explicitly trusted issuer/key settings."""
import hmac
import jwt
from fastapi import HTTPException


class NativeSparBearer:
    def __init__(self, providers, *, allowed_origins=(), cookie_prefix=''):
        self.providers = providers
        self.allowed_origins = frozenset(allowed_origins)
        self.prefix = cookie_prefix

    def __call__(self, request):
        authorization = request.headers.get('authorization')
        if authorization:
            if not authorization.startswith('Bearer '):
                raise HTTPException(401, 'Bearer authentication required')
            token = authorization[7:]
        else:
            token = request.cookies.get(self.prefix + 'X-Access-Token')
            if not token:
                raise HTTPException(401, 'Beneficiary authentication required')
            origin = request.headers.get('origin', '')
            csrf = request.cookies.get(self.prefix + 'X-CSRF-Token', '')
            supplied = request.headers.get('x-csrf-token', '')
            if origin not in self.allowed_origins or not csrf or not hmac.compare_digest(csrf.encode(), supplied.encode()):
                raise HTTPException(403, 'Cookie request origin and CSRF validation required')
        if not isinstance(token, str) or len(token) > 65536:
            raise HTTPException(401, 'Invalid identity token')
        try:
            # Unverified claims select only from operator-configured issuers;
            # they never supply discovery URLs or verification key material.
            selection = jwt.decode(token, options={'verify_signature': False})
            providers = self.providers() if callable(self.providers) else self.providers
            provider = providers.get(selection.get('iss'))
            if not provider or not provider.get('active', True):
                raise ValueError('Unconfigured issuer')
            algorithms = provider['algorithms']
            if not algorithms or set(algorithms) - {'RS256','RS384','RS512','PS256','PS384','PS512','ES256','ES384','ES512','EdDSA'}:
                raise ValueError('Asymmetric identity algorithms required')
            header = jwt.get_unverified_header(token)
            if header.get('crit') or header.get('alg') not in algorithms:
                raise ValueError('Unsupported identity header')
            key = provider['key_lookup'](header.get('kid'))
            claims = jwt.decode(token, key, algorithms=algorithms, issuer=provider['issuer'], audience=provider['audiences'], options={'require':['iss','sub','aud','exp','iat']})
            if not isinstance(claims['sub'], str) or not claims['sub']:
                raise ValueError('Missing subject')
            user_type = claims.get('user_type') or claims.get('userType')
            if user_type not in provider['user_types']:
                raise ValueError('Invalid user type')
            delegated = False
            if user_type == 'staff':
                realm = (claims.get('realm_access') or {}).get('roles') or []
                client = ((claims.get('resource_access') or {}).get('staff-portal') or {}).get('roles') or []
                if not isinstance(realm,list) or not isinstance(client,list) or 'staff' not in realm + client:
                    raise ValueError('Staff role required')
                delegated = bool(provider.get('allow_staff_mapping_resolution', False))
            return {'sub': claims['sub'], 'user_type': user_type, 'may_resolve_other_subjects': delegated}
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(401, 'Identity verification failed') from None
