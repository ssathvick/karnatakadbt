"""Bounded native webhook and SLA ticks; durable, restartable and safe to replicate."""
import datetime as dt
import hashlib
import hmac
import json
from urllib.parse import urlsplit
import httpx
from sqlalchemy import select, cast, DateTime
from approval_engine_store import objects, instant, uid, OPEN, LIVE
from approval_integrations import trusted_endpoint


class ApprovalWorkers:
    def __init__(self, store, secret_lookup, callback_origins, transport=None,
                 max_attempts=6, backoff_seconds=(60, 300, 900, 3600, 21600), timeout=10):
        if not callable(secret_lookup) or max_attempts < 1 or not backoff_seconds or any(value < 0 for value in backoff_seconds):
            raise ValueError('Explicit callback-secret adapter and valid retry settings required')
        self.store, self.secret_lookup, self.callback_origins = store, secret_lookup, set(callback_origins)
        self.transport, self.max_attempts, self.backoff_seconds, self.timeout = transport, max_attempts, backoff_seconds, timeout

    def dispatch(self, limit=20):
        store, completed = self.store, 0
        if not 1 <= limit <= 1000:
            raise ValueError('Bounded worker batch required')
        with store.engine.connect() as connection:
            identifiers = list(connection.scalars(select(objects.c.id).where(objects.c.kind == 'delivery',
                objects.c.status == 'pending', cast(objects.c.data['next_attempt_at'].as_string(), DateTime(timezone=True)) <= instant(store.clock()))
                .order_by(objects.c.at).limit(limit)))
        for identifier in identifiers:
            with store.engine.begin() as connection:
                store._lock(connection, 'delivery:' + identifier)
                delivery = store._object(connection, 'delivery', identifier)
                if delivery['status'] != 'pending' or instant(delivery['next_attempt_at']) > instant(store.clock()):
                    continue
                event = store._object(connection, 'event', delivery['event_id'], False)
                request = store._object(connection, 'request', delivery['request_id'], False)
                now = instant(store.clock())
                delivery.update(attempt=delivery['attempt'] + 1, last_attempt_at=now.isoformat(), updated_at=now.isoformat())
                if event is None or request is None:
                    delivery.update(status='exhausted', last_error='Webhook event or request is missing')
                else:
                    try:
                        parsed = urlsplit(delivery['url'])
                        if not trusted_endpoint(delivery['url'],self.callback_origins):
                            raise ValueError('Untrusted webhook origin')
                        secret = self.secret_lookup(request.get('callback_secret_id'))
                        if not isinstance(secret, str) or not secret:
                            raise ValueError('Webhook signing secret unavailable')
                        payload = event['payload']
                        body = dict(event_id=event['id'], event_type=event['event_type'], request_id=request['id'],
                            artifact_type=request['artifact_type'], artifact_id=request['artifact_id'],
                            status=payload.get('status', request['status']), stage_order=payload.get('stage_order', request['current_stage_order']),
                            actor=payload.get('actor'), occurred_at=event['created_at'])
                        raw, timestamp = json.dumps(body, separators=(',', ':')).encode(), int(now.timestamp())
                        signature = 'sha256=' + hmac.new(secret.encode(), f'{timestamp}.'.encode() + raw, hashlib.sha256).hexdigest()
                        with httpx.Client(timeout=self.timeout, trust_env=False, follow_redirects=False, transport=self.transport) as client:
                            response = client.post(delivery['url'], content=raw, headers={
                                'Content-Type': 'application/json', 'X-Approval-Event-Id': event['id'],
                                'X-Approval-Timestamp': str(timestamp), 'X-Approval-Signature': signature})
                        delivery['last_status_code'] = response.status_code
                        if response.is_success:
                            delivery.update(status='delivered', last_error=None)
                            completed += 1
                        else:
                            delivery['last_error'] = 'HTTP ' + str(response.status_code)
                    except Exception:
                        delivery.update(last_status_code=None, last_error='Webhook delivery failed')
                    if delivery['status'] != 'delivered':
                        delivery['status'] = 'exhausted' if delivery['attempt'] >= self.max_attempts else 'pending'
                        delay = self.backoff_seconds[min(delivery['attempt'] - 1, len(self.backoff_seconds) - 1)]
                        delivery['next_attempt_at'] = (now + dt.timedelta(seconds=delay)).isoformat()
                store._save(connection, 'delivery', delivery, delivery['request_id'])
        return completed

    def sla_tick(self, limit=100):
        store, expired_count = self.store, 0
        if not 1 <= limit <= 1000:
            raise ValueError('Bounded worker batch required')
        with store.engine.connect() as connection:
            candidates = list(connection.scalars(select(objects.c.parent).where(objects.c.kind == 'task',
                objects.c.status.in_(OPEN), objects.c.data['kind'].as_string() == 'approver',
                cast(objects.c.data['due_at'].as_string(), DateTime(timezone=True)) <= instant(store.clock()))
                .distinct().limit(limit)))
        for identifier in candidates:
            with store.engine.begin() as connection:
                store._lock(connection, 'request:' + identifier)
                request = store._object(connection, 'request', identifier, False)
                if request is None or request['status'] not in LIVE:
                    continue
                now = instant(store.clock())
                expired = [task for task in store._tasks(connection, request) if task['kind'] == 'approver' and task['status'] in OPEN
                           and task.get('due_at') and instant(task['due_at']) <= now]
                for task in expired:
                    task.update(status='expired', completed_at=store.clock())
                    store._save(connection, 'task', task, identifier)
                    store._emit(connection, request, 'task_expired', dict(task_id=task['id'], stage_order=task['stage_order'], assignee=task['assignee'], due_at=task['due_at']))
                    expired_count += 1
                for order in sorted({task['stage_order'] for task in expired}):
                    if request['status'] not in LIVE:
                        break
                    stage = next(value for value in request['_policy']['stages'] if value['stage_order'] == order)
                    action = stage.get('on_breach') or 'notify'
                    if action == 'escalate':
                        pairs = store._delegated(connection, store.resolver.resolve(stage.get('escalation_rules') or [], request['context']))
                        existing = {task['assignee'] for task in store._tasks(connection, request, stage) if task['status'] in OPEN}
                        due = (now + dt.timedelta(hours=stage['sla_hours'])).isoformat() if stage.get('sla_hours') else None
                        created = False
                        for who, frm in pairs:
                            if who not in existing:
                                store._new_task(connection, request, stage, who, delegated_from=frm, due=due)
                                existing.add(who); created = True
                        if created:
                            store._emit(connection, request, 'stage_escalated', dict(stage_order=order, added_approvers=[who for who, _ in pairs], actor='sla-monitor'))
                    elif action in {'auto_approve', 'auto_reject'}:
                        # Include tasks expired in this tick. The former worker
                        # expired them before selecting open tasks, so it could
                        # silently synthesize no votes and leave the flow stuck.
                        affected_ids = {task['id'] for task in expired if task['stage_order'] == order}
                        for task in store._tasks(connection, request, stage):
                            if task['kind'] != 'approver' or not (task['status'] in OPEN or task['id'] in affected_ids):
                                continue
                            vote = action.removeprefix('auto_')
                            decision = dict(id=uid(), request_id=identifier, task_id=task['id'], stage_order=order,
                                actor='sla-monitor', action=vote, comment='SLA breach auto-' + vote,
                                attachments_ref=None, created_at=store.clock(), _assignee=task['assignee'])
                            store._save(connection, 'decision', decision, identifier)
                            task.update(status='completed', completed_at=store.clock(), decision_id=decision['id'])
                            store._save(connection, 'task', task, identifier)
                        store._evaluate(connection, request, stage, 'sla-monitor', synthetic=True)
                request['updated_at'] = store.clock()
                store._save(connection, 'request', request)
        return expired_count
