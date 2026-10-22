"""Native consent lifecycle and subject recovery on the preserved SQL schema.

Identity verification and persistent receipt signing are explicit dependencies;
neither unsigned identity fallback nor ephemeral signing identities are allowed.
"""
import hashlib
from datetime import timedelta
from sqlalchemy import MetaData, Table, select, func
from native_consent_policy import NativeConsentPolicy, ConsentPolicyError, now, duration


class NativeConsentLifecycle(NativeConsentPolicy):
    def __init__(self, engine, *, verify_identity, receipt_builder):
        super().__init__(engine)
        if not callable(verify_identity) or not callable(receipt_builder):
            raise ValueError('Verified identity and persistent receipt signer required')
        self.verify_identity, self.receipt_builder = verify_identity, receipt_builder
        metadata = MetaData()
        for name in ['consent_requests', 'auth_contexts', 'consent_artefacts', 'consent_receipts', 'revocation_records', 'audit_logs']:
            self.tables[name] = Table(name, metadata, schema='public', autoload_with=engine)

    def audit(self,c,entity,identifier,action,actor,details=None):
        # Never include identity tokens, verified claims or signing material.
        return self.put(c,'audit_logs',dict(entity_type=entity,entity_id=identifier,action=action,actor=actor,details=details or {}))

    def material(self, c, partner_id):
        partner = self.one(c, 'partners', id=partner_id)
        policy = next((p for p in self.policies_in(c, partner_id) if p['status'] == 'active'), None)
        if not partner or partner['status'] != 'active' or not policy:
            raise ConsentPolicyError(404, 'partner or policy not found')
        return partner, policy

    @staticmethod
    def subject_matches(row, subject):
        return bool(subject and row['subject_id_type'] == subject.get('subject_id_type') and
                    row['subject_id_value'] == subject.get('subject_id_value'))

    def create_request(self, data):
        with self.transaction() as c:
            partner, policy = self.material(c, data['partner_id'])
            if not data['requested_scopes'] or not set(data['requested_scopes']).issubset(policy['allowed_data_scopes'] or []):
                raise ConsentPolicyError(422, 'scope_exceeds_policy')
            row=self.put(c, 'consent_requests', dict(subject_id_type=data['subject_id']['type'],
                subject_id_value=data['subject_id']['value'], controller_id=partner['controller_id'], partner_id=partner['id'],
                purpose=data['purpose'], requested_scopes=data['requested_scopes'], status='pending',
                valid_from=(data.get('validity') or {}).get('valid_from'), valid_until=(data.get('validity') or {}).get('valid_until')))
            self.audit(c,'consent_request',row['id'],'consent.request.created',partner['controller_id'])
            return row

    def request(self, identifier):
        with self.engine.connect() as c:
            return self.one(c, 'consent_requests', id=identifier)

    def pending(self, c, identifier):
        row = self.one(c, 'consent_requests', id=identifier)
        if not row:
            raise ConsentPolicyError(404, 'consent request not found')
        if row['status'] != 'pending':
            raise ConsentPolicyError(409, 'request is ' + row['status'])
        return row

    def authenticate(self, identifier, token):
        try:
            claims = self.verify_identity(token)
        except Exception:
            raise ConsentPolicyError(401, 'ID token validation failed') from None
        with self.transaction() as c:
            row = self.pending(c, identifier)
            # Both identifier type and value bind the authenticated subject.
            subject = dict(subject_id_type=claims.get('subject_id_type'),
                           subject_id_value=claims.get('subject_id_value') or claims.get('sub'))
            if not self.subject_matches(row, subject):
                raise ConsentPolicyError(403, 'token subject does not match request')
            methods = claims.get('amr')
            context=self.put(c, 'auth_contexts', dict(consent_request_id=identifier,
                auth_provider=claims['iss'], issuer=claims['iss'], auth_method=(methods[0] if methods else None) if isinstance(methods, list) else methods,
                auth_timestamp=now(), id_token_hash=hashlib.sha256(token.encode()).hexdigest(),
                token_validated=True, verified_claims=claims))
            self.audit(c,'consent_request',identifier,'consent.subject.authenticated',claims.get('sub'),{'auth_context_id':context['id']})
            return context

    def approve(self, identifier, scopes):
        with self.transaction() as c:
            row = self.pending(c, identifier)
            table = self.tables['auth_contexts']
            context = c.execute(select(table).where(table.c.consent_request_id == identifier,
                                table.c.token_validated.is_(True)).order_by(table.c.created_at.desc())).mappings().first()
            if not context:
                raise ConsentPolicyError(412, 'authentication required before approval')
            if not scopes or not set(scopes).issubset(row['requested_scopes']):
                raise ConsentPolicyError(400, 'granted scopes exceed requested scopes')
            partner, policy = self.material(c, row['partner_id'])
            effective = sorted(set(scopes) & set(policy['allowed_data_scopes'] or []))
            if not effective:
                raise ConsentPolicyError(400, 'no granted scope permitted by policy')
            stamp = now();start = row['valid_from'] or stamp;end = row['valid_until'] or stamp + timedelta(days=365)
            if end <= start or end < stamp:
                raise ConsentPolicyError(400, 'invalid consent validity')
            if policy.get('max_validity_duration') and (end-start).total_seconds() > duration(policy['max_validity_duration']):
                raise ConsentPolicyError(400, 'validity_exceeds_policy')
            if policy.get('allowed_subject_id_types') and row['subject_id_type'] not in policy['allowed_subject_id_types']:
                raise ConsentPolicyError(400, 'subject_not_allowed')
            if policy.get('allowed_purposes') and row['purpose'].get('code') not in policy['allowed_purposes']:
                raise ConsentPolicyError(400, 'purpose_not_allowed')
            artefact = self.put(c, 'consent_artefacts', dict(subject_id_type=row['subject_id_type'],
                subject_id_value=row['subject_id_value'], controller_id=row['controller_id'], partner_id=row['partner_id'],
                purpose=row['purpose'], data_scopes=row['requested_scopes'], effective_data_scopes=effective,
                fetch_type=policy['fetch_type'], valid_from=start, valid_until=end, source='originated',
                policy_version=policy['version'], auth_context_id=context['id'], status='active'))
            receipt = self.receipt_builder(artefact, partner)
            saved_receipt=self.put(c, 'consent_receipts', receipt)
            self.update(c, 'consent_requests', identifier, dict(status='approved'))
            self.audit(c,'consent',artefact['id'],'consent.granted',row['subject_id_value'],{'request_id':identifier,'receipt_id':saved_receipt['id']})
            return artefact

    def deny(self, identifier):
        with self.transaction() as c:
            row=self.pending(c, identifier)
            result=self.update(c, 'consent_requests', identifier, dict(status='denied'))
            self.audit(c,'consent_request',identifier,'consent.denied',row['subject_id_value']);return result

    def status(self, identifier):
        with self.transaction() as c:
            row = self.one(c, 'consent_artefacts', id=identifier)
            if not row:
                return None
            if row['status'] == 'active' and row['valid_until'] < now():
                row = self.update(c, 'consent_artefacts', identifier, dict(status='expired', expired_at=now()))
                self.audit(c,'consent',identifier,'consent.expired','native-expiration')
            return dict(consent_id=identifier, status=row['status'], valid_until=row['valid_until'], checked_at=now())

    def revoke(self, identifier, *, subject=None, originated_by='controller', reason=None):
        with self.transaction() as c:
            row = self.one(c, 'consent_artefacts', id=identifier)
            if not row:
                return None
            if subject is not None and not self.subject_matches(row, subject):
                raise ConsentPolicyError(403, 'forbidden')
            if row['status'] != 'active':
                raise ConsentPolicyError(409, 'consent already ' + row['status'])
            self.put(c, 'revocation_records', dict(consent_id=identifier, originated_by=originated_by, reason=reason))
            result=self.update(c, 'consent_artefacts', identifier, dict(status='revoked', revoked_at=now()))
            self.audit(c,'consent',identifier,'consent.revoked',row['subject_id_value'] if subject else originated_by)
            return result

    def subject_artefact(self, identifier, subject):
        with self.engine.connect() as c:
            row = self.one(c, 'consent_artefacts', id=identifier)
            return row if row and self.subject_matches(row, subject) else None

    def receipt(self, identifier, *, subject=None):
        with self.engine.connect() as c:
            receipt = self.one(c, 'consent_receipts', id=identifier)
            if receipt and subject is not None:
                artefact = self.one(c, 'consent_artefacts', id=receipt['consent_id'])
                if not artefact or not self.subject_matches(artefact, subject):
                    raise ConsentPolicyError(403, 'forbidden')
            return receipt

    def subject_consents(self, subject, *, status=None, page=1, size=20):
        if page < 1 or not 1 <= size <= 100:
            raise ConsentPolicyError(422, 'invalid pagination')
        table = self.tables['consent_artefacts']
        query = select(table).where(table.c.subject_id_type == subject['subject_id_type'], table.c.subject_id_value == subject['subject_id_value'])
        if status:
            query = query.where(table.c.status == status)
        with self.engine.connect() as c:
            total = c.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            rows = [dict(row) for row in c.execute(query.order_by(table.c.created_at.desc(),table.c.id).offset((page-1)*size).limit(size)).mappings()]
            return dict(items=rows, total=total, page=page, size=size, pages=max(1,(total+size-1)//size))
