"""Atomic, versioned policy storage with an audit journal and per-key locking."""
import copy
import datetime
import uuid
from sqlalchemy import (MetaData, Table, Column, String, Integer, JSON, UniqueConstraint,
                        Index, select, insert, update, text)
from approval_policy import ApprovalFailure, PolicyInput

metadata = MetaData()
policies = Table('native_approval_policies', metadata,
    Column('id', String(36), primary_key=True), Column('policy_key', String(128), nullable=False),
    Column('version', Integer, nullable=False), Column('status', String(16), nullable=False),
    Column('data', JSON, nullable=False), UniqueConstraint('policy_key', 'version'))
Index('native_approval_one_active', policies.c.policy_key, unique=True,
      postgresql_where=policies.c.status == 'active', sqlite_where=policies.c.status == 'active')
audit = Table('native_approval_audit', metadata,
    Column('id', String(36), primary_key=True), Column('actor', String(128), nullable=False),
    Column('action', String(64), nullable=False), Column('resource_id', String(180), nullable=False),
    Column('at', String, nullable=False), Column('before', JSON), Column('after', JSON),
    Column('actor_email', String(255)), Column('resource_type', String(32), nullable=False),
    Column('summary', String), Column('metadata', JSON))


class ApprovalPolicyStore:
    def __init__(self, engine, clock=None):
        self.engine = engine
        self.clock = clock or (lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def initialize(self):
        metadata.create_all(self.engine)

    def _lock(self, connection, key):
        if connection.dialect.name == 'postgresql':
            connection.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                               {'key': 'native-approval-policy:' + key})

    def _versions(self, connection, key):
        return list(connection.execute(select(policies).where(policies.c.policy_key == key)
                    .order_by(policies.c.version.desc())).mappings())

    def _get(self, connection, key, version):
        row = connection.execute(select(policies).where(policies.c.policy_key == key,
                                 policies.c.version == version)).mappings().first()
        if row is None:
            raise ApprovalFailure(404, 'AWE-001', f"Policy '{key}' v{version} not found")
        return copy.deepcopy(row['data'])

    def list(self, key=None):
        with self.engine.connect() as connection:
            if key is not None:
                versions = self._versions(connection, key)
                if not versions:
                    raise ApprovalFailure(404, 'AWE-001', f"Policy '{key}' not found")
                return [{field: row['data'][field] for field in
                         ['id', 'policy_key', 'version', 'status', 'created_at']} for row in versions]
            rows = connection.execute(select(policies).order_by(policies.c.policy_key,
                                      policies.c.version.desc())).mappings()
            latest = {}
            for row in rows:
                latest.setdefault(row['policy_key'], row['data'])
            return list(latest.values())

    def get(self, key, version):
        with self.engine.connect() as connection:
            return self._get(connection, key, version)

    def _journal(self, connection, actor, action, value, before, actor_email=None):
        key, version = value['policy_key'], value['version']
        after = value
        if action in {'activate', 'deactivate'}:
            after = {'status': value['status'], 'version': version} if action == 'activate' else {'status': 'archived'}
        summaries = {
            'create': f'Created draft {key} v{version}',
            'add_version': f'Added draft {key} v{version}',
            'update': f'Edited draft {key} v{version}',
            'activate': f'Activated {key} v{version}' +
                (f" (archived prior v{before['version']})" if action == 'activate' and before and before['version'] != version else ''),
            'deactivate': f'Deactivated {key} v{version}',
        }
        connection.execute(insert(audit).values(id=str(uuid.uuid4()), actor=actor,
            action='policy.' + action, resource_id=f"{value['policy_key']}:v{value['version']}",
            at=self.clock(), before=before, after=after, actor_email=actor_email,
            resource_type='policy', summary=summaries[action], metadata=None))

    def mutate(self, action, actor, key, version=None, payload=None, *, actor_email=None):
        if not actor or len(actor) > 128:
            raise ApprovalFailure(401, 'AWE-UNAUTHORIZED', 'Authenticated actor required')
        definition = PolicyInput.model_validate(payload).model_dump() if payload is not None else None
        if definition is not None and definition['policy_key'] != key:
            raise ApprovalFailure(400, 'AWE-010', 'policy_key in body must match URL')
        with self.engine.begin() as connection:
            self._lock(connection, key)
            before = None
            if action in {'create', 'add_version'}:
                versions = self._versions(connection, key)
                if action == 'create' and versions:
                    raise ApprovalFailure(409, 'AWE-002', 'Policy key already exists')
                if action == 'add_version' and not versions:
                    raise ApprovalFailure(404, 'AWE-001', 'No prior policy versions')
                version = versions[0]['version'] + 1 if versions else 1
                now = self.clock()
                value = dict(definition, id=str(uuid.uuid4()), version=version, status='draft',
                             created_by=actor, created_at=now, updated_at=now)
            else:
                value = self._get(connection, key, version)
                before = copy.deepcopy(value)
                if action == 'update':
                    if value['status'] != 'draft':
                        raise ApprovalFailure(409, 'AWE-007', 'Only drafts can be edited')
                    value.update(definition, created_by=actor, updated_at=self.clock())
                elif action == 'activate':
                    active = next((row for row in self._versions(connection, key) if row['status'] == 'active'), None)
                    before = {'status': 'active', 'version': active['version']} if active else None
                    if value['status'] != 'active':
                        for row in self._versions(connection, key):
                            if row['status'] == 'active':
                                prior = copy.deepcopy(row['data'])
                                prior.update(status='archived', updated_at=self.clock())
                                connection.execute(update(policies).where(policies.c.id == row['id'])
                                                   .values(status='archived', data=prior))
                        value.update(status='active', updated_at=self.clock())
                elif action == 'deactivate':
                    if value['status'] != 'active':
                        raise ApprovalFailure(409, 'AWE-007', 'Only active versions can be deactivated')
                    value.update(status='archived', updated_at=self.clock())
                    before = {'status': 'active'}
                else:
                    raise ValueError('Unsupported policy mutation')
            if action in {'create', 'add_version', 'update'}:
                orders = [stage['stage_order'] for stage in value['stages']]
                if len(orders) != len(set(orders)):
                    raise ApprovalFailure(422, 'AWE-010', 'Stage orders must be unique within a policy')
                for stage in value['stages']:
                    stage['id'] = str(uuid.uuid4())
                    if len(stage['name']) > 255:
                        raise ApprovalFailure(422, 'AWE-010', 'Stage name is too long')
                    for rule in stage['rules']:
                        rule['id'] = str(uuid.uuid4())
                    for index, rule in enumerate(stage['escalation_rules']):
                        rule['id'] = f"esc-{stage['id']}-{index}"
                value['stages'].sort(key=lambda stage: stage['stage_order'])
            if action in {'create', 'add_version'}:
                connection.execute(insert(policies).values(id=value['id'], policy_key=key,
                                   version=version, status=value['status'], data=value))
            else:
                connection.execute(update(policies).where(policies.c.id == value['id'])
                                   .values(status=value['status'], data=value))
            self._journal(connection, actor, action, value, before, actor_email)
            return value
