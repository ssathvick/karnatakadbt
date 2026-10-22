"""Custom registry adapter for the existing console's IAM HTTP contract.

IAM remains a separate migration dependency. No IAM implementation is imported.
Authentication, refresh and logout state are verified by that authoritative
service on every request. Production routing is deliberately not configured here.
"""
import hmac
import httpx
from http.cookies import SimpleCookie,CookieError
from registry_data_policy import POLICY_PATHS
from registry_route_auth import AWE_PATHS
from registry_metadata_api import RegistryPrincipal, RegistryAuthError as ConsoleAuthError


class RegistryConsoleAuthorizer:
    def __init__(self, iam_url, client_id='register-staff-portal', cookie_prefix='',
                 allowed_origins=(), csrf_enabled=True, transport=None,
                 policy_paths=None, policy_targets=None):
        self.iam_url = iam_url.rstrip('/')
        self.client_id = client_id
        self.cookie_prefix = cookie_prefix
        self.allowed_origins = frozenset(allowed_origins)
        self.csrf_enabled = csrf_enabled
        self.transport = transport
        self.policy_paths = POLICY_PATHS if policy_paths is None else frozenset(policy_paths)
        self.policy_targets = frozenset(policy_targets or {'REGISTER_RECORD','ATTRIBUTE'})

    async def __call__(self, request):
        # Browser requests must carry the same double-submit token as the
        # current console; bearer requests do not bypass this policy.
        if self.csrf_enabled and request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            cookie = request.cookies.get(self.cookie_prefix+'X-CSRF-Token', '')
            header = request.headers.get('x-csrf-token', '')
            if not cookie or not header or not hmac.compare_digest(cookie.encode(), header.encode()):
                raise ConsoleAuthError(403, 'CSRF token missing or invalid')
        origin = request.headers.get('origin')
        if origin is not None and origin not in self.allowed_origins:
            raise ConsoleAuthError(403, 'Origin is not allowed')
        forwarded = {}
        if 'authorization' in request.headers:
            forwarded['authorization'] = request.headers['authorization']
        # Only console auth cookies are forwarded. Intake-session cookies and
        # arbitrary application cookies never leave this service.
        cookies = {self.cookie_prefix+name: request.cookies[self.cookie_prefix+name]
                   for name in ['X-Access-Token','X-ID-Token','X-Session-Id']
                   if self.cookie_prefix+name in request.cookies}
        if not forwarded and not cookies:
            raise ConsoleAuthError(401, 'Authentication required')
        try:
            async with httpx.AsyncClient(timeout=10, trust_env=False, transport=self.transport) as client:
                identity = await client.get(self.iam_url+'/auth/get_user_profile',
                                            headers=forwarded, cookies=cookies, follow_redirects=False)
                request.state.registry_auth_cookies = identity.headers.get_list('set-cookie')
                if identity.status_code in {401,403}:
                    raise ConsoleAuthError(identity.status_code, 'Console session is not authorized')
                identity.raise_for_status()
                user = identity.json()
                if not isinstance(user.get('sub'), str) or not user['sub']:
                    raise ValueError('Missing authenticated subject')
                if user.get('name') is not None and not isinstance(user['name'],str):
                    raise ValueError('Invalid authenticated display name')
                roles = (user.get('client_roles') or {}).get(self.client_id, [])
                if not isinstance(roles, list) or not all(isinstance(role,str) for role in roles):
                    raise ValueError('Invalid role response')
                access = await client.post(self.iam_url+'/user-access/get_permissions_for_roles',
                                           json={'role_mnemonics': roles})
                access.raise_for_status()
                permissions = access.json().get('permissions')
                if not isinstance(permissions,list) or not all(isinstance(p,str) for p in permissions):
                    raise ValueError('Invalid permission response')
                # Keep provider-issued cookie headers only. The HTTP response
                # boundary must append these without joining Set-Cookie lines.
                request.state.registry_auth_cookies = identity.headers.get_list('set-cookie')
                policies=[];mnemonics=[];authorization=None;verified_bearer=None
                if request.url.path in self.policy_paths or request.url.path in AWE_PATHS:
                    authorization=forwarded.get('authorization');token=cookies.get(self.cookie_prefix+'X-Access-Token')
                    for header in identity.headers.get_list('set-cookie'):
                        parsed=SimpleCookie();parsed.load(header)
                        if self.cookie_prefix+'X-Access-Token' in parsed:token=parsed[self.cookie_prefix+'X-Access-Token'].value;authorization=None
                    if not authorization and token:authorization='Bearer '+token
                    if authorization and authorization.lower().startswith('bearer '):verified_bearer=authorization.split(' ',1)[1].strip() or None
                if request.url.path in self.policy_paths:
                    all_roles=user.get('client_roles') or {}
                    if not isinstance(all_roles,dict) or any(not isinstance(value,list) or not all(isinstance(role,str) for role in value) for value in all_roles.values()):raise ValueError('Invalid policy roles')
                    mnemonics=list(dict.fromkeys(role.strip() for values in all_roles.values() for role in values if role.strip().upper().startswith('DP_')))
                    if mnemonics:
                        if not authorization:raise ValueError('No verified policy token')
                        evaluated=await client.post(self.iam_url+'/data-policies/evaluate_expression',json={'policy_mnemonics':mnemonics},headers={'authorization':authorization})
                        evaluated.raise_for_status();policies=evaluated.json().get('policies')
                        if not isinstance(policies,list) or not policies or not all(isinstance(policy,dict) for policy in policies):raise ValueError('Missing authoritative policies')
                        for policy in policies:
                            if policy.get('policy_target') not in self.policy_targets or policy.get('policy_type') not in {'ALLOW','DISALLOW'} or not isinstance(policy.get('policy_filter_expression'),dict):raise ValueError('Invalid authoritative policy')
                            if policy['policy_target']=='REGISTER_RECORD' and (not isinstance(policy.get('register_id'),str) or not policy['register_id']):raise ValueError('Missing policy register')
                return RegistryPrincipal(user['sub'], frozenset(permissions), user.get('name'),tuple(policies),verified_bearer,tuple(mnemonics))
        except ConsoleAuthError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, AttributeError, KeyError,CookieError):
            raise ConsoleAuthError(503, 'Console authentication service unavailable') from None
