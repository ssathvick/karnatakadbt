"""Partner-signed consent validation without legacy business dependencies."""
import hashlib
from datetime import datetime, timezone
import jwt
from pydantic import BaseModel, ConfigDict, ValidationError, Field
from sqlalchemy import select
from native_consent_policy import duration, now


class SubjectId(BaseModel):
    type: str = Field(min_length=1)
    value: str = Field(min_length=1)


class Validity(BaseModel):
    valid_from: datetime
    valid_until: datetime


class ConsentObject(BaseModel):
    model_config = ConfigDict(extra='allow')
    jti: str = Field(min_length=1, max_length=255)
    subject_id: SubjectId
    data_controller: str
    aud: str
    purpose: dict
    data_scopes: list[str]
    fetch_type: str = 'oneshot'
    validity: Validity
    issued_at: datetime


def aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class NativeConsentVerification:
    def __init__(self, lifecycle, *, partner_key, freshness_seconds=300):
        if not callable(partner_key) or freshness_seconds <= 0:
            raise ValueError('Explicit partner key resolver and freshness window required')
        self.store, self.partner_key, self.freshness = lifecycle, partner_key, freshness_seconds

    def validate(self, payload):
        stamp = now();store = self.store;partner = policy = obj = None
        jws = payload.get('consent_jws') if isinstance(payload, dict) else None
        digest = 'sha256:' + hashlib.sha256((jws if isinstance(jws, str) else '').encode()).hexdigest()
        with store.transaction() as c:
            def deny(reason, detail):
                store.put(c, 'decision_logs', dict(partner_id=partner['id'] if partner else None,
                          object_jti=obj.jti if obj else None, decision='deny', reason_code=reason,
                          detail=detail, policy_version=policy['version'] if policy else None, request_ctx_hash=digest))
                return dict(decision='deny', reason_code=reason, detail=detail, evaluated_at=stamp)
            try:
                if not isinstance(jws, str) or len(jws) > 128*1024:
                    raise ValueError()
                header = jwt.get_unverified_header(jws)
                claims = jwt.decode(jws, options={'verify_signature': False})
                obj = ConsentObject.model_validate(claims)
                context = payload.get('request_context') or {}
                if not isinstance(context, dict):
                    raise ValueError()
                if context.get('subject_id') is not None:
                    SubjectId.model_validate(context['subject_id'])
                if context.get('requested_scopes') is not None and (not isinstance(context['requested_scopes'], list) or any(not isinstance(s,str) for s in context['requested_scopes'])):
                    raise ValueError()
            except (jwt.PyJWTError, ValueError, TypeError, ValidationError):
                return deny('malformed_object', 'consent JWS could not be decoded')
            partners = store.tables['partners']
            partner = c.execute(select(partners).where(partners.c.audience == obj.aud, partners.c.status == 'active')).mappings().first()
            if not partner:
                return deny('unknown_partner', 'partner not onboarded or suspended')
            policy = next((p for p in store.policies_in(c, partner['id']) if p['status'] == 'active'), None)
            algorithm = header.get('alg')
            if header.get('crit') or algorithm not in {'RS256','ES256','EdDSA'} or (policy and policy['allowed_signing_algs'] and algorithm not in policy['allowed_signing_algs']):
                return deny('signature_invalid', 'signing algorithm not permitted')
            try:
                key = self.partner_key(partner['partner_mgmt_id'] or partner['audience'], header.get('kid'), algorithm)
                jwt.decode(jws, key, algorithms=[algorithm], options={'verify_aud':False,'verify_exp':True})
            except Exception:
                return deny('signature_invalid', 'signature did not verify')
            # Verify signature BEFORE idempotent replay: a forged token with a
            # known jti must never disclose or reuse an existing permit.
            table = store.tables['consent_artefacts']
            existing = c.execute(select(table).where(table.c.object_jti == obj.jti)).mappings().first()
            if existing:
                logs = store.tables['decision_logs']
                prior_hash = c.execute(select(logs.c.request_ctx_hash).where(logs.c.consent_id == existing['id'], logs.c.decision == 'permit')).scalar()
                if prior_hash != digest:
                    return deny('replay', 'object identifier already used with different content')
                if existing['partner_id'] != partner['id'] or existing['subject_id_type'] != obj.subject_id.type or existing['subject_id_value'] != obj.subject_id.value:
                    return deny('replay', 'object identifier already used')
                # Request-specific scope and subject restrictions still apply.
                if context.get('subject_id') and context['subject_id'] != obj.subject_id.model_dump():
                    return deny('subject_not_allowed', 'request subject mismatch')
                if existing['status'] != 'active':
                    return deny(existing['status'], 'consent ' + existing['status'])
                if existing['valid_until'] < stamp:
                    return deny('expired','consent expired')
                scopes = set(existing['effective_data_scopes'])
                if context.get('requested_scopes'):
                    scopes &= set(context['requested_scopes'])
                if not scopes:
                    return deny('scope_exceeds_policy','no requested scope is permitted by policy')
                return dict(decision='permit', reason_code='ok', consent_id=existing['id'], subject_id=obj.subject_id.model_dump(),
                            effective_data_scopes=sorted(scopes), valid_until=existing['valid_until'], policy_version=existing['policy_version'], evaluated_at=stamp)
            if abs((stamp-aware(obj.issued_at)).total_seconds()) > self.freshness:
                return deny('replay','issued_at outside freshness window')
            if not policy:
                return deny('unknown_partner','No active policy')
            if obj.data_controller != partner['controller_id']:
                return deny('audience_mismatch','data_controller does not match partner')
            if (policy['allowed_subject_id_types'] and obj.subject_id.type not in policy['allowed_subject_id_types']) or (context.get('subject_id') and context['subject_id'] != obj.subject_id.model_dump()):
                return deny('subject_not_allowed','subject not permitted')
            if policy['allowed_purposes'] and obj.purpose.get('code') not in policy['allowed_purposes']:
                return deny('purpose_not_allowed','purpose not permitted')
            scopes = set(obj.data_scopes) & set(policy['allowed_data_scopes'] or [])
            if context.get('requested_scopes'):
                scopes &= set(context['requested_scopes'])
            if not scopes:
                return deny('scope_exceeds_policy','no requested scope is permitted by policy')
            start,end = aware(obj.validity.valid_from),aware(obj.validity.valid_until)
            if start > stamp or end < stamp or end <= start:
                return deny('expired','consent outside validity')
            if policy['max_validity_duration'] and (end-start).total_seconds() > duration(policy['max_validity_duration']):
                return deny('validity_exceeds_policy','validity longer than policy allows')
            artefact = store.put(c,'consent_artefacts',dict(subject_id_type=obj.subject_id.type,subject_id_value=obj.subject_id.value,
                controller_id=partner['controller_id'],partner_id=partner['id'],purpose=obj.purpose,data_scopes=obj.data_scopes,
                effective_data_scopes=sorted(scopes),fetch_type=obj.fetch_type,valid_from=start,valid_until=end,source='embedded',
                policy_version=policy['version'],object_jti=obj.jti,status='active'))
            receipt = store.put(c,'consent_receipts',store.receipt_builder(artefact,partner))
            store.put(c,'decision_logs',dict(partner_id=partner['id'],consent_id=artefact['id'],object_jti=obj.jti,decision='permit',
                reason_code='ok',policy_version=policy['version'],request_ctx_hash=digest))
            return dict(decision='permit',reason_code='ok',consent_id=artefact['id'],receipt_id=receipt['id'],subject_id=obj.subject_id.model_dump(),
                effective_data_scopes=sorted(scopes),valid_until=end,policy_version=policy['version'],evaluated_at=stamp)
