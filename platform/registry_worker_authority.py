"""Dedicated OAuth service identity, validated by authoritative registry IAM."""
import asyncio,threading,time
from urllib.parse import urlsplit
import httpx
from starlette.requests import Request
from registry_console_auth import RegistryConsoleAuthorizer
from registry_metadata_api import RegistryAuthError

WORKER_PERMISSIONS=frozenset({'intakeSubmission:edit','changeRequest:create'})

class WorkerAuthority:
    def __init__(self,settings,transport=None):
        self.settings=dict(settings);self.transport=transport
        for field in ['token_url','iam_url']:
            parsed=urlsplit(settings[field]);origin=parsed.scheme+'://'+parsed.netloc
            if parsed.scheme not in {'http','https'} or parsed.username or parsed.password or parsed.fragment or origin not in settings['allowed_origins']:
                raise ValueError('Explicit local worker identity origins required')
        if not settings.get('client_id') or not settings.get('client_secret') or not settings.get('subject'):
            raise ValueError('Dedicated worker identity is not configured')
        self.lock=threading.Lock();self._token=None;self._expires=0

    def token(self):
        with self.lock:
            if not self._token or time.monotonic()>=self._expires:
                try:
                    with httpx.Client(timeout=15,trust_env=False,follow_redirects=False,transport=self.transport) as client:
                        response=client.post(self.settings['token_url'],data={'grant_type':'client_credentials','client_id':self.settings['client_id'],'client_secret':self.settings['client_secret']})
                    response.raise_for_status();value=response.json();token=value.get('access_token');lifetime=float(value['expires_in'])
                    if not isinstance(token,str) or not token or lifetime<=0:raise ValueError('Invalid worker token')
                    self._token=token;self._expires=time.monotonic()+max(1,lifetime-30)
                except Exception:raise RegistryAuthError(503,'Worker identity provider unavailable') from None
            return self._token

    def __call__(self,connection,job):
        token=self.token()
        # Reuse the same identity, permission and data-policy verification as the
        # staff API. This synthetic request is internal, never a browser CSRF bypass.
        authorizer=RegistryConsoleAuthorizer(self.settings['iam_url'],csrf_enabled=False,transport=self.transport)
        request=Request({'type':'http','http_version':'1.1','method':'GET','scheme':'https',
            'path':'/change-requests/create_change_request','query_string':b'',
            'headers':[(b'authorization',('Bearer '+token).encode())],
            'server':('native-registry-worker',443),'client':('127.0.0.1',0)})
        try:principal=asyncio.run(authorizer(request))
        except RegistryAuthError:
            with self.lock:self._token=None;self._expires=0
            raise
        if principal.subject!=self.settings['subject'] or principal.permissions!=WORKER_PERMISSIONS:
            raise RegistryAuthError(403,'Worker service identity or permission scope changed')
        return principal
