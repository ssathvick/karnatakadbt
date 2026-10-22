"""Native consent receipts with retained detached-JWS and database compatibility.

Certificates come exclusively from the authenticated subject's retained key
registry. JWS headers never select remote keys or change the signed payload.
"""
import datetime
import hashlib
import hmac
import json
import uuid

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes

from native_auth_cache import AuthenticationFailure, b64, canonical, sha, unb64


def normalized_claims(transaction):
    result = {}
    for section in ['userinfo', 'id_token']:
        result[section] = {}
        for name, detail in (transaction['requestedClaims'].get(section) or {}).items():
            detail = detail or {}
            result[section][name] = {
                'value': detail.get('value'),
                'values': sorted(detail['values']) if detail.get('values') is not None else None,
                'essential': detail.get('essential', False),
            }
    return result


def consent_hash(transaction):
    """Preserve the historical wire digest; do not use it as a signature."""
    claims = {}
    for section in normalized_claims(transaction).values():
        for name in sorted(section):
            value = section[name]
            text = 'null' if value['value'] is None else value['value']
            values = 'null' if value['values'] is None else '[' + ', '.join(value['values']) + ']'
            claims[name] = ('ClaimDetail(value=' + text + ', values=' + values +
                            ', essential=' + str(value['essential']).lower() + ')')
    scopes = {name: 'false' for name in sorted(transaction['requestedAuthorizeScopes'])}
    def java_map(mapping):
        return '{' + ', '.join(k + '=' + v for k, v in mapping.items()) + '}'
    wire = '{claims=' + java_map(claims) + ', authorizeScopes=' + java_map(scopes) + '}'
    return sha(wire.strip().replace(' ', ''))


def signed_payload(transaction):
    return canonical({'accepted_claims': sorted(transaction['acceptedClaims']),
                      'permitted_authorized_scopes': sorted(transaction['permittedScopes'])})


class NativeConsent:
    def __init__(self, engine):
        self.engine = engine

    def verify(self, signature, transaction):
        try:
            if not isinstance(signature, str) or len(signature) > 16384 or signature.count('.') != 1:
                raise AuthenticationFailure('invalid_signature_format')
            header_part, signature_part = signature.split('.')
            header = json.loads(unb64(header_part))
            algorithms = ['RS256', 'RS384', 'RS512', 'PS256', 'PS384', 'PS512']
            if header.get('alg') not in algorithms or header.get('crit') or header.get('b64') is False:
                raise AuthenticationFailure('invalid_signature')
            thumbprint = header.get('x5t#S256')
            if not isinstance(thumbprint, str) or len(thumbprint) > 128:
                raise AuthenticationFailure('invalid_signature')
            individual = self.engine.cipher.decrypt(transaction['individualId'])
            with self.engine.clients.connect() as connection, connection.cursor() as cursor:
                cursor.execute('''SELECT certificate FROM esignet.public_key_registry
                    WHERE id_hash=%s AND thumbprint=%s AND expire_dtimes>NOW()
                    ORDER BY cr_dtimes DESC''', (sha(individual), thumbprint))
                certificates = [row[0] for row in cursor.fetchall()]
            if not certificates:
                raise AuthenticationFailure('invalid_signature')
            compact = header_part + '.' + b64(signed_payload(transaction)) + '.' + signature_part
            valid = False
            now = datetime.datetime.now(datetime.timezone.utc)
            for value in certificates:
                cert = x509.load_pem_x509_certificate(value.encode())
                if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
                    continue
                if not hmac.compare_digest(b64(cert.fingerprint(hashes.SHA256())), thumbprint):
                    continue
                try:
                    jwt.decode(compact, cert.public_key(), algorithms=[header['alg']],
                               options={'verify_aud': False, 'verify_exp': False})
                    valid = True
                except jwt.PyJWTError:
                    continue
            if not valid:
                raise AuthenticationFailure('invalid_signature')
            return True
        except AuthenticationFailure:
            raise
        except (ValueError, TypeError, KeyError, AttributeError):
            raise AuthenticationFailure('invalid_signature') from None

    def save(self, transaction, signature):
        self.verify(signature, transaction)
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        expires = now + datetime.timedelta(days=self.engine.settings.get('consent_days', 30))
        claims = canonical(normalized_claims(transaction)).decode()
        scopes = canonical({name: False for name in transaction['requestedAuthorizeScopes']}).decode()
        accepted = ','.join(sorted(transaction['acceptedClaims']))
        permitted = ','.join(sorted(transaction['permittedScopes']))
        digest = consent_hash(transaction)
        columns = '(id,client_id,psu_token,claims,authorization_scopes,cr_dtimes,expire_dtimes,signature,hash,accepted_claims,permitted_scopes)'
        with self.engine.clients.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',
                           ('native-consent:' + transaction['clientId'] + ':' + transaction['partnerSpecificUserToken'],))
            cursor.execute('DELETE FROM esignet.consent_detail WHERE client_id=%s AND psu_token=%s',
                           (transaction['clientId'], transaction['partnerSpecificUserToken']))
            for table in ['consent_detail', 'consent_history']:
                cursor.execute('INSERT INTO esignet.' + table + columns + ' VALUES(' + ','.join(['%s'] * 11) + ')',
                               (str(uuid.uuid4()), transaction['clientId'], transaction['partnerSpecificUserToken'],
                                claims, scopes, now, expires, signature, digest, accepted, permitted))

    def action(self, transaction, *, linked=False):
        if not (transaction['essentialClaims'] or transaction['voluntaryClaims'] or transaction['requestedAuthorizeScopes']):
            transaction['acceptedClaims'] = []
            transaction['permittedScopes'] = []
            return 'NOCAPTURE'
        with self.engine.clients.connect() as connection, connection.cursor() as cursor:
            cursor.execute('''SELECT row_to_json(t) FROM esignet.consent_detail t
                WHERE client_id=%s AND psu_token=%s AND (expire_dtimes IS NULL OR expire_dtimes>NOW())''',
                           (transaction['clientId'], transaction['partnerSpecificUserToken']))
            rows = [row[0] for row in cursor.fetchall()]
        if len(rows) != 1 or not hmac.compare_digest(rows[0]['hash'] or '', consent_hash(transaction)):
            return 'CAPTURE'
        row = rows[0]
        def parts(value):
            return value.split(',') if value else []
        accepted, permitted = parts(row['accepted_claims']), parts(row['permitted_scopes'])
        if not set(transaction['essentialClaims']) <= set(accepted):
            return 'CAPTURE'
        signed = {**transaction, 'acceptedClaims': accepted, 'permittedScopes': permitted}
        if linked:
            try:
                self.verify(row['signature'], signed)
            except AuthenticationFailure:
                return 'CAPTURE'
        transaction.update(acceptedClaims=accepted, permittedScopes=permitted)
        return 'NOCAPTURE'
