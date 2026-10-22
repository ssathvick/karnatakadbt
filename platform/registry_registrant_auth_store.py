"""Native, durable beneficiary identity authentication in the isolated candidate."""
import datetime
import hashlib
import json
import secrets
import uuid

from cryptography.fernet import Fernet
from sqlalchemy import MetaData, Table, Column, String, Text, DateTime, select, insert, update, delete, cast, literal
from sqlalchemy.dialects.postgresql import JSONB

from registry_ingest_store import RegistryIngestStore
from registry_registrant_view_store import auth_views, HISTORY_FIELDS
from registry_record_store import records
from registry_metadata_api import RegistryAuthError, RegistryPrincipal
from registry_beneficiary_oidc import BeneficiaryOIDC, IdentityFailure, authentication_details

INITIATE_PATH = '/register-data/authenticate_registrant'
CALLBACK_PATH = '/registrant-auth/callback'
SUPPORTED_PATHS = frozenset([INITIATE_PATH, CALLBACK_PATH])
metadata = MetaData()
auth_secrets = Table('console_registrant_auth_secrets', metadata,
    Column('kind', String, primary_key=True), Column('id', String, primary_key=True),
    Column('ciphertext', Text, nullable=False), Column('expires_at', DateTime))


class RegistryRegistrantAuthStore(RegistryIngestStore):
    def __init__(self, *args, registrant_auth_settings=None, identity_client=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.identity_settings = registrant_auth_settings or {}
        self.identity_client = identity_client or BeneficiaryOIDC()

    def initialize(self):
        super().initialize()
        metadata.create_all(self.engine)

    def cipher(self):
        try:
            return Fernet(self.identity_settings['encryption_key'].encode())
        except Exception:
            raise RegistryAuthError(503, 'Beneficiary identity encryption is not configured') from None

    def encrypt(self, value):
        return self.cipher().encrypt(json.dumps(value, separators=(',', ':'), default=str).encode()).decode()

    def decrypt(self, value):
        try:
            return json.loads(self.cipher().decrypt(value.encode()))
        except RegistryAuthError:
            raise
        except Exception:
            raise RegistryAuthError(503, 'Beneficiary identity state cannot be read') from None

    def secret(self, c, kind, key):
        value = c.execute(select(auth_secrets.c.ciphertext).where(auth_secrets.c.kind == kind, auth_secrets.c.id == key)).scalar_one_or_none()
        return self.decrypt(value) if value is not None else None

    def save_secret(self, c, kind, key, value, new=False, expires=None):
        attrs = {'ciphertext': self.encrypt(value), 'expires_at': expires}
        if new:
            c.execute(insert(auth_secrets).values(kind=kind, id=key, **attrs))
        else:
            c.execute(update(auth_secrets).where(auth_secrets.c.kind == kind, auth_secrets.c.id == key).values(**attrs))

    def save_attempt(self, c, value, new=False):
        self.save_secret(c, 'attempt', value['authentication_id'], value, new)
        public = {field: value.get(field) for field in HISTORY_FIELDS}
        attrs = self.auth_view_values('history', public)
        if new:
            c.execute(insert(auth_views).values(**attrs))
        else:
            c.execute(update(auth_views).where(auth_views.c.kind == 'history', auth_views.c.id == value['authentication_id']).values(**attrs))

    def execute_policy_request(self, path, p, principal, pagination=None):
        if path != INITIATE_PATH:
            return super().execute_policy_request(path, p, principal, pagination)
        if not isinstance(principal, RegistryPrincipal):
            raise ValueError('Verified authentication operator required')
        with self.engine.begin() as c:
            definition = self.require_definition(c, p['register_id'])
            if not definition.get('requires_registrant_authentication'):
                self.fail('REGISTRANT_AUTH_NOT_REQUIRED_FOR_REGISTER', 'Registrant authentication is not enabled for this register.')
            provider = self.secret(c, 'provider', p['provider_id'])
            if provider is None:
                self.fail('REGISTRANT_AUTH_PROVIDER_NOT_FOUND', 'Authentication provider not found.')
            if not provider['is_active']:
                self.fail('REGISTRANT_AUTH_PROVIDER_INACTIVE', 'Authentication provider is inactive.')
            # The retained implementation accepted providers from another
            # register. A native session must stay within its configured scope.
            if provider['register_id'] != p['register_id']:
                self.fail('REGISTRANT_AUTH_PROVIDER_NOT_FOUND', 'Authentication provider not found.')
            if not provider.get('oauth_callback_url'):
                self.fail('REGISTRANT_AUTH_PROVIDER_MISCONFIGURED', 'Authentication provider callback URL is not configured.')
            self.require_readable_subject(c, p['register_id'], p['internal_record_id'], principal.data_policies)
            member = c.execute(select(records.c.data).where(records.c.kind == 'current', records.c.register_id == p['register_id'],
                                                           records.c.record_id == p['internal_record_id'])).scalar_one()
            try:
                metadata_value = self.identity_client.metadata(provider)
                state, nonce, verifier = [secrets.token_urlsafe(32) for _ in range(3)]
                url = self.identity_client.authorization(provider, state, nonce, verifier, metadata_value)
            except IdentityFailure:
                self.fail('REGISTRANT_AUTH_PROVIDER_MISCONFIGURED', 'Authentication provider is misconfigured or unavailable.')
            now = self.clock().replace(tzinfo=None)
            auth_id = str(uuid.uuid4())
            attempt = dict.fromkeys(['user_claims', 'authentication_method', 'claim_verifications', 'token_hash', 'token_expires_at',
                                     'expiry_at', 'failure_reason', 'completed_at'])
            attempt.update(authentication_id=auth_id, register_id=p['register_id'], internal_record_id=p['internal_record_id'],
                           provider_id=p['provider_id'], initiated_by_staff_id=principal.subject,
                           initiated_at=now.isoformat(), created_at=now.isoformat(), status='PENDING')
            context = {'authentication_id': auth_id, 'provider_id': p['provider_id'], 'nonce': nonce, 'verifier': verifier,
                       'foundational_id': member.get('foundational_id') or '', 'metadata': metadata_value}
            expiry = now + datetime.timedelta(seconds=int(self.identity_settings.get('session_ttl_seconds', 300)))
            self.save_attempt(c, attempt, new=True)
            self.save_secret(c, 'transaction', hashlib.sha256(state.encode()).hexdigest(), context, new=True, expires=expiry)
            self.record_decision(c, path, auth_id, principal, stamp=now)
            return {'authentication_session_id': state, 'authorization_url': url, 'provider_name': provider['provider_name']}, None

    def complete_registrant_authentication(self, state, code):
        if len(state) > 1024 or len(code) > 8192:
            self.fail('REGISTRANT_AUTH_SESSION_INVALID_OR_EXPIRED', 'Invalid or expired authentication session.')
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        # DELETE RETURNING is an atomic get-and-pop shared across processes.
        # Commit consumption before contacting the provider to prevent code replay.
        with self.engine.begin() as c:
            row = c.execute(delete(auth_secrets).where(auth_secrets.c.kind == 'transaction', auth_secrets.c.id == state_hash)
                            .returning(auth_secrets.c.ciphertext, auth_secrets.c.expires_at)).first()
        if row is None or row.expires_at <= self.clock().replace(tzinfo=None):
            self.fail('REGISTRANT_AUTH_SESSION_INVALID_OR_EXPIRED', 'Invalid or expired authentication session.')
        context = self.decrypt(row.ciphertext)
        with self.engine.begin() as c:
            # Lock the durable attempt so accidental independent state aliases
            # cannot authenticate one attempt twice.
            encrypted = c.execute(select(auth_secrets.c.ciphertext).where(auth_secrets.c.kind == 'attempt',
                auth_secrets.c.id == context['authentication_id']).with_for_update()).scalar_one_or_none()
            if encrypted is None:
                self.fail('REGISTRANT_AUTH_RECORD_NOT_FOUND', 'Authentication record not found.')
            auth = self.decrypt(encrypted)
            if auth['status'] != 'PENDING':
                self.fail('REGISTRANT_AUTH_SESSION_INVALID_OR_EXPIRED', 'Invalid or expired authentication session.')
            provider = self.secret(c, 'provider', auth['provider_id'])
            now = self.clock().replace(tzinfo=None)
            reason = None
            if provider is None:
                reason = 'Provider not found.'
            elif not provider.get('is_active') or provider.get('register_id') != auth['register_id']:
                reason = 'Authentication provider is inactive or unavailable.'
            else:
                try:
                    tokens, claims, subject = self.identity_client.complete(provider, code, context)
                    foundational = str(context['foundational_id'])
                    if not foundational:
                        raise IdentityFailure('Registrant record does not have a foundational_id; cannot verify authentication.')
                    if not subject:
                        raise IdentityFailure('Token subject is missing; cannot verify against registrant record.')
                    if subject.strip() != foundational.strip():
                        raise IdentityFailure('Token subject does not match registrant record.')
                    definition = self.require_definition(c, auth['register_id'])
                    validity = int(definition['registrant_authentication_validity_days'])
                    auth.update(status='SUCCESS', user_claims=self.encrypt(claims),
                                token_hash=hashlib.sha256(tokens['id_token'].encode()).hexdigest(),
                                expiry_at=(now + datetime.timedelta(days=validity)).isoformat())
                    auth['authentication_method'], auth['claim_verifications'] = authentication_details(claims)
                    if isinstance(tokens.get('expires_in'), int) and not isinstance(tokens['expires_in'], bool):
                        auth['token_expires_at'] = (now + datetime.timedelta(seconds=tokens['expires_in'])).isoformat()
                    interface = self.record_interface(definition)
                    columns = interface['current']['columns'] if interface and interface.get('current') else {}
                    fields = {'last_authentication_id': auth['authentication_id'], 'last_authenticated_at': now.isoformat(),
                              'last_authentication_status': 'SUCCESS', 'authentication_expiry_at': auth['expiry_at'],
                              'authentication_expiry_notified': False, 'authentication_token': claims.get('sub')}
                    if all(field in columns for field in fields):
                        expression = records.c.data.op('||')(literal(fields, type_=JSONB))
                        c.execute(update(records).where(records.c.kind == 'current', records.c.register_id == auth['register_id'],
                            records.c.record_id == auth['internal_record_id']).values(data=expression, source_json=cast(expression, Text)))
                except IdentityFailure as error:
                    reason = str(error)
                except Exception:
                    reason = 'Authentication completion failed.'
            if reason:
                auth.update(status='FAILURE', failure_reason=reason, user_claims=None, token_hash=None,
                            authentication_method=None, claim_verifications=None, expiry_at=None, token_expires_at=None)
            auth['completed_at'] = now.isoformat()
            self.save_attempt(c, auth)
            self.record_decision(c, CALLBACK_PATH, auth['authentication_id'],
                                 RegistryPrincipal(auth['initiated_by_staff_id'], frozenset()), reason, now)
            return {field: auth[field] for field in ['authentication_id', 'status', 'failure_reason']}
