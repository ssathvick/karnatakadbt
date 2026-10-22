"""Native approver resolution and read-only Keycloak administration adapters."""
from urllib.parse import quote, urlsplit
import httpx
from json_logic import jsonLogic
from approval_policy import ApprovalFailure

def trusted_endpoint(value,allowed_origins):
    parsed=urlsplit(value)
    if parsed.username or parsed.password or parsed.fragment or f'{parsed.scheme}://{parsed.netloc}' not in allowed_origins:
        return False
    if parsed.scheme=='https':return bool(parsed.hostname)
    # Existing in-cluster integrations use service DNS over the private mesh.
    # HTTP is allowed only for explicitly configured cluster service origins.
    host=parsed.hostname or ''
    return parsed.scheme=='http' and host not in {'localhost','metadata'} and (
        host.endswith('.svc.cluster.local') or ('.' not in host and '-' in host and host.replace('-','').isalnum()))


def assignee(user):
    return next((str(user[key]).strip() for key in ['preferred_username', 'username', 'sub', 'id']
                 if user.get(key) and str(user[key]).strip()), None)


class ApprovalDirectory:
    def __init__(self, base_url, realm, client_id, client_secret, transport=None):
        parsed = urlsplit(base_url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Trusted HTTPS identity-provider origin required')
        self.base, self.realm = base_url.rstrip('/'), quote(realm, safe='')
        self.client_id, self.client_secret, self.transport = client_id, client_secret, transport

    def get(self, path, params=None):
        try:
            with httpx.Client(timeout=10, trust_env=False, follow_redirects=False, transport=self.transport) as client:
                response = client.post(f'{self.base}/realms/{self.realm}/protocol/openid-connect/token',
                    data={'grant_type': 'client_credentials', 'client_id': self.client_id, 'client_secret': self.client_secret})
                response.raise_for_status()
                response = client.get(f'{self.base}/admin/realms/{self.realm}{path}',
                    params=params or {}, headers={'Authorization': 'Bearer ' + response.json()['access_token']})
                response.raise_for_status()
                if len(response.content) > 4 * 1024 * 1024:
                    raise ValueError('Oversized directory response')
                return response.json()
        except Exception:
            raise ApprovalFailure(503, 'AWE-011', 'Identity directory request failed') from None

    def client_uuid(self, client):
        found = self.get('/clients', {'clientId': client})
        if not found:
            raise ApprovalFailure(503, 'AWE-011', 'Identity client not found')
        return quote(found[0]['id'], safe='')

    def pick(self, kind, q=None, limit=100, client=None):
        if kind == 'users':
            raw = self.get('/users', dict(max=limit, **({'search': q.strip()} if q and q.strip() else {})))
            return [{'user_id': assignee(user), 'username': user.get('username') or assignee(user),
                     'email': user.get('email') or None,
                     'name': ' '.join(str(user.get(field) or '').strip() for field in ['firstName', 'lastName']).strip() or None}
                    for user in raw if assignee(user)]
        if kind == 'clients':
            return sorted([{'client_id': value['clientId'], 'name': value.get('name') or value['clientId']}
                           for value in self.get('/clients', {'max': limit}) if value.get('clientId')],
                          key=lambda value: value['client_id'].lower())
        if kind == 'roles':
            scope = client.strip() if client and client.strip() else None
            path = '/clients/' + self.client_uuid(scope) + '/roles' if scope else '/roles'
            return sorted([{'name': value['name'], 'client': scope, 'description': value.get('description') or None}
                           for value in self.get(path) if value.get('name') and
                           (not q or not q.strip() or q.strip().lower() in value['name'].lower())],
                          key=lambda value: value['name'].lower())
        if kind == 'groups':
            raw = self.get('/groups', dict(max=limit, **({'search': q.strip()} if q and q.strip() else {})))
            found = {}
            def flatten(items):
                for item in items:
                    if item.get('path'):
                        found.setdefault(item['path'], {'path': item['path'], 'name': item.get('name') or item['path']})
                    flatten(item.get('subGroups') or [])
            flatten(raw)
            return sorted(found.values(), key=lambda value: value['path'].lower())
        raise ValueError('Unsupported directory picker')

    def members(self, rule_type, value):
        if rule_type == 'role':
            prefix = '/clients/' + self.client_uuid(value['client']) if value.get('client') else ''
            path = prefix + '/roles/' + quote(value['role'], safe='') + '/users'
        else:
            group = self.get('/group-by-path/' + quote(value['group'].lstrip('/'), safe='/'))
            path = '/groups/' + quote(group['id'], safe='') + '/members'
        found, first = [], 0
        while True:
            page = self.get(path, {'first': first, 'max': 200})
            for user in page:
                identity = assignee(user)
                if identity is None:
                    raise ApprovalFailure(503, 'AWE-007', 'Directory user has no assignee identity')
                found.append(identity)
            if len(page) < 200:
                return found
            first += len(page)
            if first > 100000:
                raise ApprovalFailure(503, 'AWE-007', 'Directory membership exceeds configured safety bound')


class ApproverResolver:
    def __init__(self, directory=None, allowed_http_origins=(), transport=None):
        self.directory, self.allowed_http_origins, self.transport = directory, set(allowed_http_origins), transport

    def skip(self, stage, context):
        try:
            return bool(stage.get('skip_if') and jsonLogic(stage['skip_if'], context))
        except Exception:
            return False

    def resolve(self, rules, context):
        result = []
        try:
            for rule in rules:
                kind, value = rule['rule_type'], rule.get('rule_value') or {}
                if kind == 'user':
                    identities = [value['user_id']]
                elif kind in {'role', 'group'}:
                    if self.directory is None:
                        raise ValueError('Identity directory required')
                    identities = self.directory.members(kind, value)
                elif kind == 'expression':
                    outcome = jsonLogic(value['logic'], context) if value.get('logic') is not None else None
                    identities = [outcome] if isinstance(outcome, str) else [str(item) for item in outcome if item] if isinstance(outcome, list) else []
                elif kind == 'http':
                    parsed = urlsplit(value['url'])
                    origin = f'{parsed.scheme}://{parsed.netloc}'
                    if not trusted_endpoint(value['url'],self.allowed_http_origins):
                        raise ValueError('Resolver origin is not authorized')
                    with httpx.Client(timeout=5, trust_env=False, follow_redirects=False, transport=self.transport) as client:
                        response = client.post(value['url'], json={'context': context})
                        response.raise_for_status()
                        if len(response.content) > 1024 * 1024:
                            raise ValueError('Oversized resolver response')
                        identities = response.json().get('user_ids') or []
                else:
                    raise ValueError('Unsupported rule type')
                for identity in identities:
                    if not isinstance(identity, str) or not identity:
                        raise ValueError('Resolver returned an invalid assignee')
                    if identity not in result:
                        result.append(identity)
            return result
        except Exception:
            raise ApprovalFailure(503, 'AWE-007', 'Approver resolution failed') from None
