"""Encrypted external-issuance intents and responses retained across retries."""
import hashlib
import time

from native_certify_authorization import CredentialAuthorizationFailure
from native_certify_sunbird import SunbirdIssuer


class ExternalIssuance:
    def __init__(self, issuance):
        self.issuance = issuance
        self.authorization = issuance.authorization
        self.configuration = issuance.configuration

    def settings(self, configuration):
        return self.issuance.settings.get('external_issuers', {}).get(configuration['credential_config_key_id'])

    def issue(self, configuration, document, session_id, nonce, expires_at):
        settings = self.settings(configuration)
        if settings is None:
            return None
        if settings.get('kind') != 'sunbird' or configuration['credential_format'] != 'ldp_vc':
            raise CredentialAuthorizationFailure('unsupported_external_issuer')
        # The same holder nonce always reuses the same durable request/response.
        identifier = hashlib.sha256(('sunbird:' + session_id + ':' + nonce).encode()).hexdigest()
        with self.configuration.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('external-issuance:' + identifier,))
            cursor.execute('SELECT configuration_id,content,expires_at FROM certify.native_external_issuance WHERE id=%s FOR UPDATE', (identifier,))
            row = cursor.fetchone()
            if row:
                if row[0] != configuration['credential_config_key_id'] or row[2] <= time.time():
                    raise CredentialAuthorizationFailure('invalid_session')
                state = self.authorization.open(row[1], identifier)
                # IDs and timestamps belong to the first durable attempt. All
                # identity, holder, issuer, type and status content must match.
                volatile = {'id', 'issuanceDate', 'expirationDate', 'validFrom', 'validUntil'}
                if {k: v for k, v in state['document'].items() if k not in volatile} != {k: v for k, v in document.items() if k not in volatile}:
                    raise CredentialAuthorizationFailure('external_issuance_intent_mismatch')
            else:
                state = {'document': document}
                cursor.execute('INSERT INTO certify.native_external_issuance(id,configuration_id,content,expires_at) VALUES(%s,%s,%s,%s)',
                    (identifier, configuration['credential_config_key_id'], self.authorization.seal(state, identifier), expires_at))
        if 'credential' not in state:
            # Durable intent is committed before the external network request.
            # Providers must honor Idempotency-Key when a request is retried.
            if settings.get('idempotency_supported') is not True:
                raise CredentialAuthorizationFailure('external_issuer_requires_idempotency', status=503)
            credential = SunbirdIssuer(settings).issue(state['document'], self.issuance.proofs, idempotency_key=identifier)
            state['credential'] = credential
            with self.configuration.connect() as connection, connection.cursor() as cursor:
                cursor.execute('UPDATE certify.native_external_issuance SET content=%s WHERE id=%s',
                               (self.authorization.seal(state, identifier), identifier))
        return SunbirdIssuer(settings).verify(state['document'], state['credential'], self.issuance.proofs)
