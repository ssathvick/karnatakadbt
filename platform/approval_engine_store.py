"""Independent durable approval state machine, tasks, decisions and transactional outbox."""
import copy
import datetime as dt
import json
import math
import uuid
from sqlalchemy import Table, Column, String, JSON, Index, select, insert, update, delete
from approval_policy_store import ApprovalPolicyStore, metadata, policies, audit
from approval_policy import ApprovalFailure
from approval_integrations import ApproverResolver

objects = Table('native_approval_objects', metadata,
    Column('id', String(180), primary_key=True), Column('kind', String(24), nullable=False),
    Column('parent', String(180)), Column('status', String(24)), Column('actor', String(128)),
    Column('at', String, nullable=False), Column('data', JSON, nullable=False))
Index('native_approval_parent', objects.c.kind, objects.c.parent)
Index('native_approval_assignee', objects.c.kind, objects.c.actor, objects.c.status)
Index('native_approval_order', objects.c.kind, objects.c.at)
OPEN = {'open', 'claimed'}
LIVE = {'pending', 'in_review'}


def uid():
    return str(uuid.uuid4())


def instant(value):
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)


def search_text(request):
    context, values = request.get('context') or {}, []
    priority = ['record_name', 'register_mnemonic', 'section_mnemonic', 'intake_form_mnemonic', 'change_request_id', 'submission_id']
    def stringify(value):
        if value is None:
            return ''
        return json.dumps(value, sort_keys=True, default=str) if isinstance(value, (dict, list)) else str(value).strip()
    for field in priority:
        if stringify(context.get(field)):
            values.append(stringify(context[field]))
    for field in sorted(context):
        if field not in priority and not isinstance(context[field], (dict, list)) and stringify(context[field]):
            values.append(stringify(context[field]))
    if not any(stringify(context.get(field)) for field in ['change_request_id', 'submission_id']) and request['artifact_id'].strip():
        values.append(request['artifact_id'].strip())
    return ' '.join(values).strip() or None


class ApprovalEngineStore(ApprovalPolicyStore):
    def __init__(self, engine, clock=None, resolver=None):
        super().__init__(engine, clock)
        self.resolver = resolver or ApproverResolver()

    def _save(self, connection, kind, value, parent=None):
        record = dict(id=value['id'], kind=kind, parent=parent, status=value.get('status'),
                      actor=value.get('assignee') or value.get('actor') or value.get('user_id'),
                      at=value.get('created_at') or self.clock(), data=value)
        exists = connection.scalar(select(objects.c.id).where(objects.c.id == value['id']))
        if exists:
            connection.execute(update(objects).where(objects.c.id == value['id']).values(**record))
        else:
            connection.execute(insert(objects).values(**record))

    def _object(self, connection, kind, identifier, required=True):
        value = connection.scalar(select(objects.c.data).where(objects.c.kind == kind, objects.c.id == identifier))
        if value is None and required:
            code = 'AWE-003' if kind == 'request' else 'AWE-004' if kind in {'task', 'delegation'} else 'AWE-007'
            raise ApprovalFailure(404, code, f'{kind.title()} not found')
        return copy.deepcopy(value)

    def _items(self, connection, kind, parent=None):
        query = select(objects.c.data).where(objects.c.kind == kind)
        if parent is not None:
            query = query.where(objects.c.parent == parent)
        return [copy.deepcopy(value) for value in connection.scalars(query.order_by(objects.c.at))]

    def request_out(self, value):
        return {key: item for key, item in value.items() if not key.startswith('_') and key != 'callback_secret_id'}

    def task_out(self, value, request=None, decision=None):
        out = {key: item for key, item in value.items() if not key.startswith('_') and key != 'search_text'}
        out.update(decision_action=decision['action'] if decision else None,
                   decision_comment=decision.get('comment') if decision else None,
                   context=request['context'] if request else None,
                   artifact_type=request['artifact_type'] if request else None,
                   artifact_id=request['artifact_id'] if request else None,
                   policy_key=request['policy_key'] if request else None,
                   search_text=search_text(request) if request else value.get('search_text'))
        return out

    def _audit(self, connection, identity, action, kind, identifier, summary, before=None, after=None, extra=None):
        connection.execute(insert(audit).values(id=uid(), actor=identity.subject, actor_email=identity.email,
            action=action, resource_type=kind, resource_id=identifier, summary=summary,
            before=before, after=after, metadata=extra, at=self.clock()))

    def _emit(self, connection, request, event_type, payload):
        body = dict(payload, request_id=request['id'], artifact_type=request['artifact_type'],
                    artifact_id=request['artifact_id'], status=request['status'])
        body.setdefault('stage_order', request['current_stage_order'])
        now = self.clock()
        event = dict(id=uid(), request_id=request['id'], event_type=event_type, payload=body, created_at=now)
        self._save(connection, 'event', event, request['id'])
        if request.get('callback_url'):
            delivery = dict(id=uid(), event_id=event['id'], request_id=request['id'], event_type=event_type,
                url=request['callback_url'], status='pending', attempt=0, next_attempt_at=now,
                last_attempt_at=None, last_status_code=None, last_error=None, created_at=now, updated_at=now)
            self._save(connection, 'delivery', delivery, request['id'])
        return event

    def _tasks(self, connection, request, stage=None):
        return [task for task in self._items(connection, 'task', request['id'])
                if stage is None or task['stage_order'] == stage['stage_order']]

    def _new_task(self, connection, request, stage, who, kind='approver', delegated_from=None, required=False, due=None):
        now = self.clock()
        value = dict(id=uid(), request_id=request['id'], stage_id=stage['id'], stage_order=stage['stage_order'],
            assignee=who, assignee_name=None, kind=kind, delegated_from=delegated_from, reassigned_from=None,
            status='open', claimed_at=None, completed_at=None, due_at=due, decision_id=None,
            created_at=now, search_text=search_text(request), _required=required)
        self._save(connection, 'task', value, request['id'])
        return value

    def _delegated(self, connection, users):
        now, choices, pairs = instant(self.clock()), {}, []
        for value in reversed(self._items(connection, 'delegation')):
            if instant(value['starts_at']) <= now < instant(value['ends_at']):
                choices.setdefault(value['user_id'], value['delegate_to'])
        for user in users:
            target = choices.get(user, user)
            if target not in [pair[0] for pair in pairs]:
                pairs.append((target, user if target != user else None))
        return pairs

    @staticmethod
    def _group(stage):
        return ('group', stage['parallel_group']) if stage.get('parallel_group') is not None else ('stage', stage['stage_order'])

    def _advance(self, connection, request, after=0, actor=None):
        policy, stages = request['_policy'], request['_policy']['stages']
        groups = []
        for stage in stages:
            if not groups or self._group(groups[-1][0]) != self._group(stage):
                groups.append([stage])
            else:
                groups[-1].append(stage)
        for group in groups:
            if group[0]['stage_order'] <= after:
                continue
            started = False
            prior = {decision.get('_assignee', decision['actor']) for decision in self._items(connection, 'decision', request['id'])
                     if decision['action'] == 'approve' and decision['stage_order'] < group[0]['stage_order']}
            def permitted(who):
                return not ((policy['forbid_self_approval'] and who == request['requester']) or
                            (policy['forbid_repeat_approvers'] and who in prior))
            for stage in group:
                if self.resolver.skip(stage, request['context']):
                    self._emit(connection, request, 'stage_skipped', {'stage_order': stage['stage_order'], 'reason': 'skip_if'})
                    continue
                rules = stage['rules']
                approvers = [who for who in self.resolver.resolve([rule for rule in rules if rule['kind'] == 'approver'], request['context']) if permitted(who)]
                observers = self.resolver.resolve([rule for rule in rules if rule['kind'] == 'observer'], request['context'])
                required = {who for who in self.resolver.resolve([rule for rule in rules if rule['kind'] == 'approver' and rule['required']], request['context']) if permitted(who)}
                pairs = [(who, frm) for who, frm in self._delegated(connection, approvers) if permitted(who)]
                required_targets = {who for who, _ in self._delegated(connection, sorted(required)) if permitted(who)}
                observer_pairs = self._delegated(connection, observers)
                if not pairs:
                    if stage['on_empty'] == 'skip':
                        self._emit(connection, request, 'stage_skipped', {'stage_order': stage['stage_order'], 'reason': 'no_approvers'})
                        continue
                    request.update(status='rejected', completed_at=self.clock())
                    self._emit(connection, request, 'request_rejected', {'reason': 'no_approvers_resolved', 'stage_order': stage['stage_order']})
                    return
                due = (instant(self.clock()) + dt.timedelta(hours=stage['sla_hours'])).isoformat() if stage.get('sla_hours') else None
                for who, frm in pairs:
                    self._new_task(connection, request, stage, who, delegated_from=frm, required=who in required_targets, due=due)
                for who, frm in observer_pairs:
                    self._new_task(connection, request, stage, who, 'observer', frm)
                self._emit(connection, request, 'stage_started', {'stage_order': stage['stage_order'], 'name': stage['name'],
                    'mode': stage['mode'], 'mode_value': stage['mode_value'], 'approvers': [who for who, _ in pairs],
                    'observers': [who for who, _ in observer_pairs], 'required_approvers': sorted(required)})
                started = True
            if started:
                active = [task['stage_order'] for task in self._tasks(connection, request) if task['kind'] == 'approver' and task['status'] in OPEN]
                if active:
                    request['current_stage_order'] = min(active)
                request['status'] = 'in_review'
                return
        request.update(status='approved', completed_at=self.clock())
        self._emit(connection, request, 'request_approved', dict(reason='all_stages_skipped', **({'actor': actor} if actor else {})))

    def simulate(self, key, version, context):
        policy, results = self.get(key, version), []
        for stage in policy['stages']:
            skip = self.resolver.skip(stage, context)
            results.append(dict(stage_order=stage['stage_order'], name=stage['name'], mode=stage['mode'],
                mode_value=stage['mode_value'], resolved_approvers=[] if skip else self.resolver.resolve(stage['rules'], context),
                skipped=skip, skip_reason='skip_if' if skip else None))
        return dict(policy_id=policy['id'], policy_version=version, stages=results)

    def start(self, identity, payload, idempotency_key=None):
        with self.engine.begin() as connection:
            if idempotency_key:
                self._lock(connection, 'idempotency:' + identity.subject + ':' + idempotency_key)
                import hashlib
                identifier = 'idem:' + hashlib.sha256((identity.subject + ':' + idempotency_key).encode()).hexdigest()
                prior = self._object(connection, 'idempotency', identifier, False)
                if prior:
                    compared=copy.deepcopy(payload)
                    if prior.get('_legacy_payload'):
                        compared['requester']=compared.get('requester') or identity.subject
                    if prior['payload'] != compared:
                        raise ApprovalFailure(409, 'AWE-009', 'Idempotency key reused with a different request')
                    return prior['response']
            self._lock(connection, payload['policy_key'])
            active = next((row for row in self._versions(connection, payload['policy_key']) if row['status'] == 'active'), None)
            if not active:
                raise ApprovalFailure(404, 'AWE-001', 'No active policy')
            now, policy = self.clock(), active['data']
            request = dict(id=uid(), policy_id=policy['id'], policy_key=policy['policy_key'], policy_version=policy['version'],
                artifact_type=payload['artifact_type'], artifact_id=payload['artifact_id'], source_service=identity.subject,
                requester=payload.get('requester') or identity.subject, context=payload.get('context') or {},
                status='pending', current_stage_order=1, callback_url=payload.get('callback_url'),
                callback_secret_id=payload.get('callback_secret_id'), completed_at=None, created_at=now, updated_at=now,
                _policy=copy.deepcopy(policy))
            self._emit(connection, request, 'request_created', {'policy_key': policy['policy_key'], 'policy_version': policy['version']})
            if not policy['stages']:
                request.update(status='approved', completed_at=self.clock())
                self._emit(connection, request, 'request_approved', {'actor': request['requester']})
            else:
                self._advance(connection, request, actor=request['requester'])
            self._save(connection, 'request', request)
            out = dict(request_id=request['id'], status=request['status'], current_stage_order=request['current_stage_order'],
                       tasks=[self.task_out(task) for task in self._tasks(connection, request) if task['stage_order'] == request['current_stage_order']])
            if idempotency_key:
                self._save(connection, 'idempotency', dict(id=identifier, payload=payload, response=out,
                    _legacy_key=idempotency_key,_owner=identity.subject,created_at=self.clock()))
            return out

    def _close(self, connection, request, orders):
        for task in self._tasks(connection, request):
            if task['stage_order'] in orders and task['status'] in OPEN:
                task.update(status='skipped', completed_at=self.clock())
                self._save(connection, 'task', task, request['id'])

    def _outcome(self, connection, request, stage):
        tasks = [task for task in self._tasks(connection, request, stage) if task['kind'] == 'approver' and task['status'] != 'reassigned']
        decisions = {item['id']: item for item in self._items(connection, 'decision', request['id'])}
        votes = [decisions[task['decision_id']]['action'] for task in tasks if task.get('decision_id') in decisions]
        approvals, available = votes.count('approve'), sum(task['status'] in OPEN for task in tasks)
        if 'reject' in votes:
            return 'rejected'
        mode = stage['mode']
        needed = len(tasks) if mode == 'all' else math.ceil((stage.get('mode_value') or 100) / 100 * len(tasks)) if mode == 'percentage' else stage.get('mode_value') or 1
        if approvals >= needed:
            missing = [task for task in tasks if task.get('_required') and
                       (task.get('decision_id') not in decisions or decisions[task['decision_id']]['action'] != 'approve')]
            if missing:
                return 'open' if any(task['status'] in OPEN for task in missing) else 'rejected'
            return 'approved'
        return 'rejected' if mode != 'all' and approvals + available < needed else 'open'

    def _evaluate(self, connection, request, stage, actor, synthetic=False):
        outcome = self._outcome(connection, request, stage)
        if outcome == 'open':
            return
        stages = request['_policy']['stages']
        group = [item for item in stages if self._group(item) == self._group(stage)]
        if outcome == 'rejected':
            self._close(connection, request, {item['stage_order'] for item in group})
            request.update(status='rejected', completed_at=self.clock())
            self._emit(connection, request, 'stage_completed', {'stage_order': stage['stage_order'], 'outcome': 'rejected'})
            self._emit(connection, request, 'request_rejected', {'actor': actor})
            return
        self._close(connection, request, {stage['stage_order']})
        self._emit(connection, request, 'stage_completed', dict(stage_order=stage['stage_order'], outcome='approved', **({} if synthetic else {'actor': actor})))
        # Expired tasks are closed but do not constitute approval. In a
        # parallel group, advance only after every non-skipped stage has
        # actually satisfied its own quorum and required-approver rules.
        if all(not any(task['kind'] == 'approver' for task in self._tasks(connection, request, item)) or
               self._outcome(connection, request, item) == 'approved' for item in group):
            self._advance(connection, request, max(item['stage_order'] for item in group), actor)

    def task_action(self, identity, identifier, action, payload=None):
        payload = payload or {}
        with self.engine.begin() as connection:
            first = self._object(connection, 'task', identifier)
            self._lock(connection, 'request:' + first['request_id'])
            task = self._object(connection, 'task', identifier)
            request = self._object(connection, 'request', task['request_id'])
            if action != 'reassign' and task['assignee'] != (identity.assignee_id or identity.subject) and 'AWE_ADMIN' not in identity.roles:
                raise ApprovalFailure(403, 'AWE-008', 'Task is not assigned to you')
            if request['status'] not in LIVE or task['status'] not in OPEN or (action == 'claim' and task['status'] != 'open'):
                raise ApprovalFailure(409, 'AWE-007', 'Task or request is not open')
            if action == 'claim':
                task.update(status='claimed', claimed_at=self.clock())
                self._save(connection, 'task', task, request['id'])
                return self.task_out(task)
            if action == 'reassign':
                if 'AWE_ADMIN' not in identity.roles:
                    raise ApprovalFailure(403, 'AWE-008', 'Administrator required')
                if task['assignee'] == payload['new_assignee']:
                    raise ApprovalFailure(409, 'AWE-007', 'Assignee is unchanged')
                task.update(status='reassigned', completed_at=self.clock())
                self._save(connection, 'task', task, request['id'])
                stage = next(item for item in request['_policy']['stages'] if item['stage_order'] == task['stage_order'])
                new = self._new_task(connection, request, stage, payload['new_assignee'], task['kind'], required=task.get('_required', False), due=task['due_at'])
                new['reassigned_from'] = task['assignee']
                self._save(connection, 'task', new, request['id'])
                self._emit(connection, request, 'task_reassigned', dict(task_id=task['id'], new_task_id=new['id'], stage_order=task['stage_order'],
                    **{'from': task['assignee'], 'to': new['assignee']}, actor=identity.subject, reason=payload.get('reason')))
                self._audit(connection, identity, 'task.reassign', 'task', task['id'],
                    f"Reassigned stage-{task['stage_order']} task from {task['assignee']} to {new['assignee']}" + (f" ({payload['reason']})" if payload.get('reason') else ''),
                    {'assignee': task['assignee'], 'status': 'open'}, {'assignee': new['assignee'], 'status': 'open', 'new_task_id': new['id']},
                    {'request_id': request['id'], 'reason': payload.get('reason')})
                return self.task_out(new)
            decision = dict(id=uid(), request_id=request['id'], task_id=task['id'], stage_order=task['stage_order'],
                actor=identity.name or identity.subject, action=payload['action'], comment=payload.get('comment'),
                attachments_ref=payload.get('attachments_ref'), created_at=self.clock(), _assignee=task['assignee'])
            self._save(connection, 'decision', decision, request['id'])
            task.update(status='completed', completed_at=self.clock(), decision_id=decision['id'],
                        assignee_name=identity.name or identity.assignee_id or identity.subject)
            self._save(connection, 'task', task, request['id'])
            if task['kind'] == 'approver':
                stage = next(item for item in request['_policy']['stages'] if item['stage_order'] == task['stage_order'])
                self._evaluate(connection, request, stage, decision['actor'])
            request['updated_at'] = self.clock()
            self._save(connection, 'request', request)
            return {key: value for key, value in decision.items() if not key.startswith('_')}

    def cancel(self, identity, identifier, reason=None):
        with self.engine.begin() as connection:
            self._lock(connection, 'request:' + identifier)
            request = self._object(connection, 'request', identifier)
            if request['status'] not in LIVE:
                raise ApprovalFailure(409, 'AWE-007', 'Request is terminal')
            before = request['status']
            request.update(status='cancelled', completed_at=self.clock(), updated_at=self.clock())
            self._close(connection, request, {task['stage_order'] for task in self._tasks(connection, request)})
            self._emit(connection, request, 'request_cancelled', {'actor': identity.subject, 'reason': reason})
            self._save(connection, 'request', request)
            self._audit(connection, identity, 'request.cancel', 'request', identifier,
                f"Cancelled {request['artifact_type']}/{request['artifact_id']}" + (f' ({reason})' if reason else ''),
                {'status': before}, {'status': 'cancelled'}, {'reason': reason, 'artifact_id': request['artifact_id']})
            return self.request_out(request)

    def delegation(self, identity, payload=None, identifier=None):
        with self.engine.begin() as connection:
            if identifier:
                self._lock(connection, 'delegation:' + identifier)
                value = self._object(connection, 'delegation', identifier)
                connection.execute(delete(objects).where(objects.c.kind == 'delegation', objects.c.id == identifier))
                before = {key: value[key] for key in ['user_id', 'delegate_to', 'starts_at', 'ends_at']}
                self._audit(connection, identity, 'delegation.delete', 'delegation', identifier,
                    f"Deleted delegation {value['user_id']} → {value['delegate_to']}", before)
                return None
            now = self.clock()
            value = dict(payload, id=uid(), created_by=identity.subject, created_at=now, updated_at=now)
            self._save(connection, 'delegation', value)
            after = {key: value[key] for key in ['user_id', 'delegate_to', 'starts_at', 'ends_at']}
            self._audit(connection, identity, 'delegation.create', 'delegation', value['id'],
                f"Delegate {value['user_id']} → {value['delegate_to']} ({value['starts_at']} — {value['ends_at']})",
                after=after, extra={'reason': value.get('reason')})
            return value

    def retry_delivery(self, identity, identifier):
        with self.engine.begin() as connection:
            self._lock(connection, 'delivery:' + identifier)
            value = self._object(connection, 'delivery', identifier)
            if value['status'] == 'delivered':
                raise ApprovalFailure(409, 'AWE-007', 'Delivery already succeeded')
            before = {key: value[key] for key in ['status', 'attempt', 'last_status_code', 'last_error']}
            value.update(status='pending', attempt=0, next_attempt_at=self.clock(), last_error=None, last_status_code=None, updated_at=self.clock())
            self._save(connection, 'delivery', value, value['request_id'])
            self._audit(connection, identity, 'delivery.retry', 'delivery', identifier,
                f"Retried delivery {identifier[:8]}… ({value['event_type']})", before,
                {'status': 'pending', 'attempt': 0}, {'request_id': value['request_id']})
            return value
