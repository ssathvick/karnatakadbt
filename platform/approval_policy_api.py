"""Standalone candidate API; requires an explicitly supplied trusted authenticator."""
from dataclasses import dataclass
import datetime
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from approval_policy import ApprovalFailure, PolicyInput


@dataclass(frozen=True)
class ApprovalIdentity:
    subject: str
    roles: frozenset[str]
    email: str | None = None
    assignee_id: str | None = None
    name: str | None = None


def create_policy_app(store, authenticate):
    if not callable(authenticate):
        raise ValueError('A trusted authentication adapter is mandatory')
    app = FastAPI(title='Native approval engine candidate')

    @app.exception_handler(ApprovalFailure)
    async def approval_error(request, error):
        return JSONResponse(status_code=error.status, content={
            'id': 'openg2p.awe', 'version': '1.0',
            'responsetime': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'response': None, 'errors': [{'errorCode': error.code, 'message': error.message}]})

    @app.middleware('http')
    async def cache_headers(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def gate(admin=False):
        def authorize(request: Request):
            token = request.headers.get('authorization', '')
            if not token.startswith('Bearer ') or not token[7:]:
                raise HTTPException(401, 'Missing bearer token')
            identity = authenticate(token[7:])
            if not isinstance(identity, ApprovalIdentity) or not identity.subject:
                raise HTTPException(401, 'Invalid bearer token')
            allowed = {'AWE_ADMIN'} if admin else {'AWE_ADMIN', 'AWE_VIEWER'}
            if not allowed.intersection(identity.roles):
                raise HTTPException(403, 'Approval role required')
            return identity
        return authorize

    admin, viewer = gate(True), gate()
    base = '/v1/awe/policies'

    @app.get(base)
    def list_policies(identity=Depends(viewer)):
        return store.list()

    @app.post(base, status_code=201)
    def create(payload: PolicyInput, identity=Depends(admin)):
        return store.mutate('create', identity.subject, payload.policy_key,
                            payload=payload.model_dump(), actor_email=identity.email)

    @app.get(base + '/{policy_key}/versions')
    def versions(policy_key: str, identity=Depends(viewer)):
        return store.list(policy_key)

    @app.get(base + '/{policy_key}/versions/{version}')
    def get(policy_key: str, version: int, identity=Depends(viewer)):
        return store.get(policy_key, version)

    @app.put(base + '/{policy_key}', status_code=201)
    def add(policy_key: str, payload: PolicyInput, identity=Depends(admin)):
        return store.mutate('add_version', identity.subject, policy_key,
                            payload=payload.model_dump(), actor_email=identity.email)

    @app.patch(base + '/{policy_key}/versions/{version}')
    def edit(policy_key: str, version: int, payload: PolicyInput, identity=Depends(admin)):
        return store.mutate('update', identity.subject, policy_key, version, payload.model_dump(), actor_email=identity.email)

    @app.post(base + '/{policy_key}/versions/{version}/activate')
    def activate(policy_key: str, version: int, identity=Depends(admin)):
        return store.mutate('activate', identity.subject, policy_key, version, actor_email=identity.email)

    @app.post(base + '/{policy_key}/versions/{version}/deactivate')
    def deactivate(policy_key: str, version: int, identity=Depends(admin)):
        return store.mutate('deactivate', identity.subject, policy_key, version, actor_email=identity.email)

    return app
