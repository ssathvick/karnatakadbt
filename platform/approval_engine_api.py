"""All 32 approval-engine operations assembled with explicit authentication."""
import datetime as dt
import math
from typing import Any
from fastapi import Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select, func, cast, String, DateTime, or_, text
from approval_policy import ApprovalFailure
from approval_policy_api import ApprovalIdentity, create_policy_app
from approval_policy_store import audit
from approval_engine_store import objects, instant
from approval_integrations import trusted_endpoint


class ContextInput(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)


class RequestInput(ContextInput):
    policy_key: str = Field(max_length=128)
    artifact_type: str = Field(max_length=128)
    artifact_id: str = Field(max_length=255)
    callback_url: str | None = None
    callback_secret_id: str | None = None
    requester: str | None = None


class DecisionInput(BaseModel):
    action: str
    comment: str | None = None
    attachments_ref: str | None = None

    @field_validator('action')
    @classmethod
    def valid_action(cls, value):
        if value not in {'approve', 'reject', 'abstain'}:
            raise ValueError('Unsupported decision action')
        return value


class ReassignInput(BaseModel):
    new_assignee: str = Field(min_length=1, max_length=128)
    reason: str | None = None


class CancelInput(BaseModel):
    reason: str | None = None
    actor: str | None = None


class DelegationInput(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    delegate_to: str = Field(min_length=1, max_length=128)
    starts_at: dt.datetime
    ends_at: dt.datetime
    reason: str | None = None

    @model_validator(mode='after')
    def valid_window(self):
        self.starts_at, self.ends_at = instant(self.starts_at), instant(self.ends_at)
        if self.ends_at <= self.starts_at or self.user_id == self.delegate_to:
            raise ValueError('A delegation requires distinct users and a positive time window')
        return self


def create_engine_app(store, authenticate, directory=None, public_config=None, callback_origins=()):
    app = create_policy_app(store, authenticate)
    public = {'service_id': 'openg2p.awe', 'api_version': '1.0', 'module': 'registry',
              'webhook': {'max_attempts': 6, 'backoff_seconds': [60, 300, 900, 3600, 21600], 'timeout_seconds': 10},
              'sla': {'check_interval_seconds': 300}}
    if public_config:
        for key in ['service_id', 'api_version', 'module', 'webhook', 'sla']:
            if key in public_config:
                if key in {'webhook', 'sla'}:
                    public[key] = {field: public_config[key].get(field, default)
                                   for field, default in public[key].items()}
                else:
                    public[key] = public_config[key]

    def gate(role=None):
        def authorize(request: Request):
            value = request.headers.get('authorization', '')
            if not value.startswith('Bearer ') or not value[7:]:
                raise HTTPException(401, 'Missing bearer token')
            identity = authenticate(value[7:])
            if not isinstance(identity, ApprovalIdentity) or not identity.subject:
                raise HTTPException(401, 'Invalid bearer token')
            allowed = {'AWE_ADMIN'} if role == 'admin' else {'AWE_ADMIN', 'AWE_VIEWER'}
            if role and not allowed.intersection(identity.roles):
                raise HTTPException(403, 'Approval role required')
            return identity
        return authorize

    authenticated, admin, viewer = gate(), gate('admin'), gate('viewer')
    base = '/v1/awe'

    def envelope(value):
        return dict(id='openg2p.awe', version='1.0', responsetime=store.clock(), response=value, errors=[])

    @app.get(base + '/health')
    def health():
        try:
            with store.engine.connect() as connection:
                connection.execute(text('SELECT 1'))
                connection.execute(select(objects.c.id).limit(1))
            return envelope({'status': 'UP'})
        except Exception:
            return JSONResponse(status_code=503, content=dict(envelope(None), errors=[{'errorCode': 'AWE-006', 'message': 'Approval database unavailable'}]))

    @app.get(base + '/version')
    def version():
        return envelope({'service_version': 'native-approval-1.0', 'build_time': 'local', 'git_commit': 'local'})

    @app.get(base + '/config')
    def config():
        return envelope(public)

    @app.post(base + '/policies/{policy_key}/versions/{version}/simulate')
    def simulate(policy_key: str, version: int, payload: ContextInput, identity=Depends(viewer)):
        return store.simulate(policy_key, version, payload.context)

    @app.post(base + '/requests', status_code=201)
    def create_request(payload: RequestInput, identity=Depends(authenticated),
                       idempotency_key: str | None = Header(default=None, alias='Idempotency-Key')):
        if payload.callback_url:
            from urllib.parse import urlsplit
            parsed = urlsplit(payload.callback_url)
            if not trusted_endpoint(payload.callback_url,callback_origins):
                raise ApprovalFailure(400, 'AWE-010', 'Callback origin is not authorized')
        return store.start(identity, payload.model_dump(), idempotency_key)

    @app.get(base + '/requests')
    def requests(artifact_type: str | None = None, artifact_id: str | None = None,
                 status: str | None = None, limit: int = Query(default=50, ge=1, le=500), identity=Depends(authenticated)):
        query = select(objects.c.data).where(objects.c.kind == 'request')
        for key, value in [('artifact_type', artifact_type), ('artifact_id', artifact_id)]:
            if value:
                query = query.where(objects.c.data[key].as_string() == value)
        if status:
            query = query.where(objects.c.status == status)
        with store.engine.connect() as connection:
            return [store.request_out(value) for value in connection.scalars(query.order_by(objects.c.at.desc()).limit(limit))]

    @app.get(base + '/requests/{request_id}')
    def get_request(request_id: str, identity=Depends(authenticated)):
        with store.engine.connect() as connection:
            return store.request_out(store._object(connection, 'request', request_id))

    @app.post(base + '/requests/{request_id}/cancel')
    def cancel(request_id: str, payload: CancelInput, identity=Depends(admin)):
        return store.cancel(identity, request_id, payload.reason)

    @app.get(base + '/requests/{request_id}/events')
    def events(request_id: str, identity=Depends(authenticated)):
        with store.engine.connect() as connection:
            return store._items(connection, 'event', request_id)

    def filtered_tasks(identity, assignee='me', request_id=None, status=None, artifact_type=None, policy_key=None, search=None):
        query = select(objects.c.data).where(objects.c.kind == 'task')
        if assignee == 'me':
            query = query.where(objects.c.actor == (identity.assignee_id or identity.subject))
        elif assignee and assignee != '*':
            query = query.where(objects.c.actor == assignee)
        if request_id:
            query = query.where(objects.c.parent == request_id)
        if status:
            query = query.where(objects.c.status == status)
        if artifact_type or policy_key or search:
            parent = objects.alias('parent_request')
            condition = (parent.c.id == objects.c.parent) & (parent.c.kind == 'request')
            if artifact_type:
                condition &= parent.c.data['artifact_type'].as_string() == artifact_type
            if policy_key:
                condition &= parent.c.data['policy_key'].as_string() == policy_key
            if search:
                pattern = '%' + search.strip() + '%'
                condition &= or_(objects.c.data['search_text'].as_string().ilike(pattern),
                                 cast(parent.c.data['context'], String).ilike(pattern))
            query = query.where(select(parent.c.id).where(condition).exists())
        return query

    @app.get(base + '/tasks/stats')
    def task_stats(status: str | None = None, identity=Depends(authenticated)):
        parent = objects.alias('stats_request')
        query = select(parent.c.data['artifact_type'].as_string(), func.count(objects.c.id)).select_from(
            objects.join(parent, (parent.c.id == objects.c.parent) & (parent.c.kind == 'request'))).where(
            objects.c.kind == 'task', objects.c.actor == (identity.assignee_id or identity.subject))
        if status:
            query = query.where(objects.c.status == status)
        with store.engine.connect() as connection:
            counts = dict(connection.execute(query.group_by(parent.c.data['artifact_type'].as_string())).all())
        return dict(total=sum(counts.values()), change_request_count=counts.get('registry.change_request', 0),
                    intake_form_count=counts.get('registry.intake_form', 0))

    @app.get(base + '/tasks')
    def tasks(assignee: str | None = 'me', request_id: str | None = None, status: str | None = None,
              artifact_type: str | None = None, policy_key: str | None = None, search_text: str | None = None,
              page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100), identity=Depends(authenticated)):
        query = filtered_tasks(identity, assignee, request_id, status, artifact_type, policy_key, search_text)
        with store.engine.connect() as connection:
            total = connection.scalar(select(func.count()).select_from(query.subquery()))
            result = []
            for value in connection.scalars(query.order_by(objects.c.at.desc()).offset((page - 1) * page_size).limit(page_size)):
                request = store._object(connection, 'request', value['request_id'])
                decision = store._object(connection, 'decision', value['decision_id'], False) if value.get('decision_id') else None
                result.append(store.task_out(value, request, decision))
        return dict(items=result, total=total, page=page, page_size=page_size, pages=math.ceil(total / page_size) if total else 1)

    @app.post(base + '/tasks/{task_id}/claim')
    def claim(task_id: str, identity=Depends(authenticated)):
        return store.task_action(identity, task_id, 'claim')

    @app.post(base + '/tasks/{task_id}/decision', status_code=201)
    def decide(task_id: str, payload: DecisionInput, identity=Depends(authenticated)):
        return store.task_action(identity, task_id, 'decision', payload.model_dump())

    @app.post(base + '/tasks/{task_id}/reassign')
    def reassign(task_id: str, payload: ReassignInput, identity=Depends(admin)):
        return store.task_action(identity, task_id, 'reassign', payload.model_dump())

    @app.get(base + '/admin/deliveries')
    def deliveries(status: str | None = None, request_id: str | None = None,
                   limit: int = Query(default=100, ge=1, le=500), identity=Depends(viewer)):
        query = select(objects.c.data).where(objects.c.kind == 'delivery')
        if status:
            query = query.where(objects.c.status == status)
        if request_id:
            query = query.where(objects.c.parent == request_id)
        with store.engine.connect() as connection:
            return list(connection.scalars(query.order_by(objects.c.at.desc()).limit(limit)))

    @app.post(base + '/admin/deliveries/{delivery_id}/retry')
    def retry(delivery_id: str, identity=Depends(admin)):
        return store.retry_delivery(identity, delivery_id)

    @app.get(base + '/admin/audit')
    def audit_list(actor: str | None = None, action: str | None = None, resource_type: str | None = None,
                   resource_id: str | None = None, since: dt.datetime | None = None, until: dt.datetime | None = None,
                   limit: int = Query(default=100, ge=1, le=1000), identity=Depends(viewer)):
        query = select(audit)
        for key, value in [('actor', actor), ('action', action), ('resource_type', resource_type), ('resource_id', resource_id)]:
            if value:
                query = query.where(audit.c[key] == value)
        if since:
            query = query.where(cast(audit.c.at, DateTime(timezone=True)) >= instant(since))
        if until:
            query = query.where(cast(audit.c.at, DateTime(timezone=True)) < instant(until))
        with store.engine.connect() as connection:
            return [dict(id=value['id'], occurred_at=value['at'], actor=value['actor'], actor_email=value['actor_email'],
                action=value['action'], resource_type=value['resource_type'], resource_id=value['resource_id'],
                summary=value['summary'], before=value['before'], after=value['after'], metadata_=value['metadata'])
                for value in connection.execute(query.order_by(audit.c.at.desc()).limit(limit)).mappings()]

    def picker(kind, **params):
        if directory is None:
            raise ApprovalFailure(503, 'AWE-011', 'Identity directory is not configured')
        return directory.pick(kind, **params)

    @app.get(base + '/admin/keycloak/users')
    def users(q: str | None = None, limit: int = Query(default=100, ge=1, le=200), identity=Depends(viewer)):
        return picker('users', q=q, limit=limit)

    @app.get(base + '/admin/keycloak/clients')
    def clients(limit: int = Query(default=200, ge=1, le=500), identity=Depends(viewer)):
        return picker('clients', limit=limit)

    @app.get(base + '/admin/keycloak/roles')
    def roles(client: str | None = None, q: str | None = None, identity=Depends(viewer)):
        return picker('roles', client=client, q=q)

    @app.get(base + '/admin/keycloak/groups')
    def groups(q: str | None = None, limit: int = Query(default=100, ge=1, le=200), identity=Depends(viewer)):
        return picker('groups', q=q, limit=limit)

    @app.get(base + '/delegations')
    def delegations(user_id: str | None = None, limit: int = Query(default=100, ge=1, le=500), identity=Depends(viewer)):
        query = select(objects.c.data).where(objects.c.kind == 'delegation')
        if user_id:
            query = query.where(objects.c.actor == user_id)
        with store.engine.connect() as connection:
            return list(connection.scalars(query.order_by(cast(objects.c.data['starts_at'].as_string(), DateTime(timezone=True)).desc()).limit(limit)))

    @app.post(base + '/delegations', status_code=201)
    def create_delegation(payload: DelegationInput, identity=Depends(admin)):
        value = payload.model_dump()
        value.update(starts_at=payload.starts_at.isoformat(), ends_at=payload.ends_at.isoformat())
        return store.delegation(identity, value)

    @app.delete(base + '/delegations/{delegation_id}', status_code=204)
    def delete_delegation(delegation_id: str, identity=Depends(admin)):
        store.delegation(identity, identifier=delegation_id)
        return Response(status_code=204)

    return app
