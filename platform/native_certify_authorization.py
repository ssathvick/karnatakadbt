"""Native confidential offers and single-use credential authorization.

Claims are AES-GCM encrypted before SQL storage. A row lock serializes code
redemption; failed transaction-code attempts commit without consuming the code.
"""
import base64
import datetime
import hashlib
import hmac
import json
import math
import re
import secrets
import time
import uuid
from urllib.parse import urlencode

import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography import x509
from native_keymanager import VaultFailure


PREAUTH = 'urn:ietf:params:oauth:grant-type:pre-authorized_code'


class CredentialAuthorizationFailure(ValueError):
    def __init__(self, error, *, status=400, extra=None):
        self.error, self.status, self.extra = error, status, extra or {}
        super().__init__(error)


def encode(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def digest(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096:
        raise CredentialAuthorizationFailure('invalid_request')
    return hashlib.sha256(value.encode()).hexdigest()


class CertifyAuthorization:
    def __init__(self, configuration, crypto, settings):
        self.configuration, self.crypto, self.settings = configuration, crypto, settings
        self.aead = AESGCM(base64.b64decode(settings['state_key'], validate=True))

    def seal(self, value, identifier):
        nonce = secrets.token_bytes(12)
        return nonce + self.aead.encrypt(nonce, json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode(),
                                         ('native-certify-session-v1:' + identifier).encode())

    def open(self, value, identifier):
        value = bytes(value)
        return json.loads(self.aead.decrypt(value[:12], value[12:], ('native-certify-session-v1:' + identifier).encode()))

    def active_configuration(self, identifier):
        try:
            configuration = self.configuration.get(identifier)
        except VaultFailure:
            raise CredentialAuthorizationFailure('invalid_credential_configuration_id') from None
        if str(configuration['status']).lower() != 'active':
            raise CredentialAuthorizationFailure('invalid_credential_configuration_id')
        return configuration

    def create_offer(self, body):
        if not isinstance(body, dict) or not isinstance(body.get('claims'), dict) or not body['claims']:
            raise CredentialAuthorizationFailure('invalid_request')
        configuration = self.active_configuration(body.get('credential_configuration_id'))
        expires = body.get('expires_in', 600)
        if type(expires) is not int or not 60 <= expires <= 86400:
            raise CredentialAuthorizationFailure('invalid_request')
        transaction_code = body.get('tx_code')
        if transaction_code is not None and (not isinstance(transaction_code, str) or not re.fullmatch('[A-Za-z0-9]{4,8}', transaction_code)):
            raise CredentialAuthorizationFailure('invalid_request')
        if len(json.dumps(body['claims'])) > 512 * 1024:
            raise CredentialAuthorizationFailure('invalid_request')
        code, offer = secrets.token_urlsafe(48), str(uuid.uuid4())
        identifier = digest(code)
        salt = secrets.token_bytes(32)
        verifier = hashlib.pbkdf2_hmac('sha256', transaction_code.encode(), salt, 600000) if transaction_code else None
        payload = {'claims': body['claims'], 'configuration': configuration['credential_config_key_id'],
                   'code': code, 'scope': configuration['scope'], 'tx_length': len(transaction_code or ''),
                   'offer': offer, 'created_at': int(time.time()),
                   'tx_mode': 'numeric' if transaction_code and transaction_code.isdigit() else 'text',
                   # Retain only inside authenticated encryption so a controlled
                   # original-binary rollback can restore a pending code check.
                   'tx_code': transaction_code}
        with self.configuration.connect() as connection, connection.cursor() as cursor:
            cursor.execute('''INSERT INTO certify.native_authorization
                (id,offer_hash,kind,content,expires_at,tx_salt,tx_hash) VALUES(%s,%s,%s,%s,%s,%s,%s)''',
                (identifier, digest(offer), 'PREAUTH', self.seal(payload, identifier), int(time.time()) + expires, salt, verifier))
        return {'credential_offer_uri': self.configuration.settings['issuer'] + '/v1/certify/credential-offer-data/' + offer}

    def offer(self, offer):
        with self.configuration.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT id,content,expires_at,used_at FROM certify.native_authorization WHERE offer_hash=%s', (digest(offer),))
            row = cursor.fetchone()
        if row is None or row[2] <= time.time() or row[3] is not None:
            raise CredentialAuthorizationFailure('invalid_request', status=404)
        payload = self.open(row[1], row[0])
        grant = {'pre-authorized_code': payload['code']}
        if payload['tx_length']:
            grant['tx_code'] = {'length': payload['tx_length'], 'input_mode': payload['tx_mode']}
        return {'credential_issuer': self.configuration.settings['issuer'],
                'credential_configuration_ids': [payload['configuration']], 'grants': {PREAUTH: grant}}

    def sign(self, claims):
        row, key, certificate = self.crypto.signing_key({'applicationId': 'CERTIFY_SERVICE'})
        return jwt.encode(claims, key, algorithm=row['algorithm'], headers={'kid': self.crypto.engine.jose_id(row)})

    def token(self, form):
        grant = form.get('grant_type')
        if grant not in [PREAUTH, 'authorization_code']:
            raise CredentialAuthorizationFailure('unsupported_grant_type')
        code = form.get('pre-authorized_code') if grant == PREAUTH else form.get('code')
        identifier, rejected, result = digest(code), None, None
        with self.configuration.connect() as connection, connection.cursor() as cursor:
            cursor.execute('''SELECT content,kind,expires_at,used_at,tx_salt,tx_hash,attempts
                              FROM certify.native_authorization WHERE id=%s FOR UPDATE''', (identifier,))
            row = cursor.fetchone()
            if row is None or row[2] <= time.time() or row[3] is not None or row[6] >= 5 or row[1] != ('PREAUTH' if grant == PREAUTH else 'IAR'):
                rejected = 'invalid_grant'
            else:
                payload = self.open(row[0], identifier)
                if row[5] is not None:
                    supplied = form.get('tx_code', '')
                    if not isinstance(supplied, str) or len(supplied) > 128:
                        supplied = ''
                    actual = hashlib.pbkdf2_hmac('sha256', supplied.encode(), bytes(row[4]), 600000)
                    if not hmac.compare_digest(actual, bytes(row[5])):
                        rejected = 'invalid_grant'
                if grant == 'authorization_code':
                    verifier = form.get('code_verifier', '')
                    if form.get('client_id') != payload['client_id'] or not re.fullmatch('[A-Za-z0-9._~-]{43,128}', verifier) or not hmac.compare_digest(encode(hashlib.sha256(verifier.encode()).digest()), payload['code_challenge']):
                        rejected = 'invalid_grant'
                if rejected:
                    cursor.execute('UPDATE certify.native_authorization SET attempts=attempts+1 WHERE id=%s', (identifier,))
                else:
                    configuration = self.active_configuration(payload['configuration'])
                    now, session, nonce = int(time.time()), secrets.token_urlsafe(48), secrets.token_urlsafe(32)
                    session_id = digest(session)
                    ttl = min(3600, max(1, int(row[2]) - now))
                    token = self.sign({'iss': self.configuration.settings['issuer'],
                                       'aud': self.configuration.settings['issuer'] + '/v1/certify/issuance/credential',
                                       'iat': now, 'exp': now + ttl, 'jti': session, 'scope': configuration['scope'],
                                       'sub': 'urn:karnatakadbt:credential-session:' + session_id,
                                       'c_nonce': nonce, 'c_nonce_expires_in': ttl,
                                       'client_id': form.get('client_id') or 'pre-authorized-wallet'})
                    payload.pop('code', None)
                    payload.update(nonce=nonce, nonce_issued_at=now, client_id=form.get('client_id') or 'pre-authorized-wallet')
                    payload['access_token_hash'] = encode(hashlib.sha256(token.encode()).digest()[:16])
                    cursor.execute('''INSERT INTO certify.native_credential_session(id,content,expires_at)
                                      VALUES(%s,%s,%s)''', (session_id, self.seal(payload, session_id), now + ttl))
                    cursor.execute('UPDATE certify.native_authorization SET used_at=%s WHERE id=%s', (now, identifier))
                    if grant == 'authorization_code':
                        cursor.execute('UPDATE certify.iar_session SET is_code_used=true,code_used_at=now() WHERE authorization_code=%s', (identifier,))
                    result = {'access_token': token, 'token_type': 'Bearer', 'expires_in': ttl,
                              'scope': configuration['scope'], 'c_nonce': nonce, 'c_nonce_expires_in': ttl}
        if rejected:
            raise CredentialAuthorizationFailure(rejected)
        return result

    def access_session(self, compact):
        try:
            header = jwt.get_unverified_header(compact)
            row, certificate = self.verification_key(header.get('kid'),header.get('alg'))
            if header.get('crit'):
                raise ValueError()
            value = jwt.decode(compact, certificate.public_key(), algorithms=[row['algorithm']],
                               issuer=self.configuration.settings['issuer'], audience=self.configuration.settings['issuer'] + '/v1/certify/issuance/credential',
                               options={'require': ['exp', 'iat', 'iss', 'aud', 'jti', 'scope', 'client_id']})
            identifier=digest(value['jti'])
            with self.configuration.connect() as connection,connection.cursor() as cursor:
                cursor.execute('SELECT content,expires_at FROM certify.native_credential_session WHERE id=%s',(identifier,))
                session=cursor.fetchone()
            if session and (session[1]<=time.time() or self.open(session[0],identifier).get('revoked_at') is not None):
                raise CredentialAuthorizationFailure('invalid_token',status=401)
            if self.settings.get('allow_imported_source_cache') is True:
                with self.configuration.connect() as connection, connection.cursor() as cursor:
                    cursor.execute('SELECT 1 FROM certify.native_credential_session WHERE id=%s',(identifier,))
                    exists=cursor.fetchone() is not None
                if not exists:
                    # A native token may have survived a legacy detour. Its
                    # imported cache is keyed by token hash, not native jti.
                    return self._retained_session(compact,value,cache_only=True)
            return identifier, value
        except (ValueError, TypeError, KeyError, jwt.PyJWTError):
            if self.settings.get('allow_imported_original_tokens'):
                return self.original_session(compact)
            raise CredentialAuthorizationFailure('invalid_token', status=401) from None

    def verification_key(self,kid,algorithm):
        if not isinstance(kid,str) or not 1<=len(kid)<=128:
            raise ValueError('Invalid signing identity')
        self.crypto.engine.policy('CERTIFY_SERVICE','')
        with self.crypto.engine.vault.connect() as connection:
            if connection.execute("SELECT 1 FROM km_disabled WHERE application='CERTIFY_SERVICE' AND reference='' ").fetchone():
                raise ValueError('Signing scope revoked')
            rows=connection.execute("""SELECT k.*,c.certificate FROM vault_keys k JOIN km_certificates c ON c.key_id=k.id
                WHERE k.application='CERTIFY_SERVICE' AND k.reference='' AND k.state IN ('ACTIVE','VERIFY_ONLY')""").fetchall()
        matches=[dict(row) for row in rows if self.crypto.engine.jose_id(row)==kid]
        if len(matches)!=1 or matches[0]['algorithm']!=algorithm:
            raise ValueError('Unknown or revoked signing identity')
        row=matches[0];cert=x509.load_pem_x509_certificate(row['certificate'].encode())
        if not cert.not_valid_before_utc.timestamp()<=time.time()<cert.not_valid_after_utc.timestamp():
            raise ValueError('Signing certificate outside validity')
        return row,cert

    def revoke_session(self,identifier,*,at=None):
        if not isinstance(identifier,str) or re.fullmatch('[a-f0-9]{64}',identifier) is None:
            raise ValueError('Explicit credential-session identity required')
        at=time.time() if at is None else at
        if type(at) not in (int,float) or not math.isfinite(at) or not 0<at<=time.time()+5:
            raise ValueError('Valid revocation time required')
        with self.configuration.connect() as connection,connection.cursor() as cursor:
            cursor.execute('SELECT content FROM certify.native_credential_session WHERE id=%s FOR UPDATE',(identifier,))
            row=cursor.fetchone()
            if row is None:raise CredentialAuthorizationFailure('invalid_token',status=401)
            state=self.open(row[0],identifier)
            if state.get('revoked_at') is not None:at=min(at,state['revoked_at'])
            state['revoked_at']=at
            cursor.execute('UPDATE certify.native_credential_session SET content=%s WHERE id=%s',(self.seal(state,identifier),identifier))
        return at

    def original_claims(self, compact):
        """Verify the retained 0.14 token encoding without relaxing normal JWTs.

        That binary serializes a base64url payload but signs its decoded bytes
        under b64=false. Compatibility is confined to explicitly imported token
        fingerprints or explicitly imported cache hashes; this parser alone
        never authorizes a session.
        """
        from native_credential_proofs import verify_signature
        try:
            if not isinstance(compact, str) or len(compact) > 65536:
                raise ValueError()
            header, payload, signature = compact.split('.')
            def decode(segment):
                raw = base64.b64decode(segment + '=' * (-len(segment) % 4), altchars=b'-_', validate=True)
                if encode(raw) != segment:
                    raise ValueError()
                return raw
            def object_pairs(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError()
                    result[key] = value
                return result
            parameters = json.loads(decode(header), object_pairs_hook=object_pairs)
            row, certificate = self.verification_key(parameters.get('kid'),parameters.get('alg'))
            if parameters != {'alg': row['algorithm'], 'kid': self.crypto.engine.jose_id(row), 'b64': False, 'crit': ['b64']}:
                raise ValueError()
            raw = decode(payload)
            verify_signature(certificate.public_key(), row['algorithm'], decode(signature), header.encode() + b'.' + raw)
            claims = json.loads(raw, object_pairs_hook=object_pairs)
            now = time.time()
            if not isinstance(claims, dict) or type(claims.get('exp')) is not int or type(claims.get('iat')) is not int:
                raise ValueError()
            if not claims['iat'] <= now + 5 or not now < claims['exp'] <= claims['iat'] + 3600:
                raise ValueError()
            if claims.get('iss') != self.configuration.settings['issuer'] or claims.get('aud') != self.configuration.settings['issuer'] + '/v1/certify/issuance/credential':
                raise ValueError()
            if not isinstance(claims.get('scope'), str) or not isinstance(claims.get('client_id'), str):
                raise ValueError()
            return claims
        except Exception:
            raise CredentialAuthorizationFailure('invalid_token', status=401) from None

    def original_session(self, compact):
        claims = self.original_claims(compact)
        return self._retained_session(compact,claims)

    def _retained_session(self,compact,claims,*,cache_only=False):
        # Both callers have already verified signature, issuer and audience.
        # This path never imports a bearer token or creates a session.
        identifier = digest(compact)
        imported_hash = False
        with self.configuration.connect() as connection, connection.cursor() as cursor:
            if cache_only:row=None
            else:
                cursor.execute('SELECT content,expires_at FROM certify.native_credential_session WHERE id=%s', (identifier,))
                row = cursor.fetchone()
            if row is None and self.settings.get('allow_imported_source_cache') is True:
                # Original caches retain at_hash, not the plaintext bearer token.
                # Only a root-imported, encrypted cache record can enable this
                # path. The original signature/issuer/audience were verified
                # above; at_hash cryptographically binds that exact token.
                token_hash = encode(hashlib.sha256(compact.encode()).digest()[:16])
                identifier = digest('source-access:' + token_hash)
                cursor.execute('SELECT content,expires_at FROM certify.native_credential_session WHERE id=%s', (identifier,))
                row = cursor.fetchone()
                imported_hash = row is not None
        if row is None or row[1] <= time.time():
            raise CredentialAuthorizationFailure('invalid_token', status=401)
        state = self.open(row[0], identifier)
        if state.get('revoked_at') is not None:
            raise CredentialAuthorizationFailure('invalid_token',status=401)
        if imported_hash:
            cache_fingerprint = state.get('source_cache_sha256')
            if state.get('imported_original_cache') is not True or state.get('access_token_hash') != token_hash or not isinstance(cache_fingerprint, str) or not re.fullmatch('[0-9a-f]{64}', cache_fingerprint):
                raise CredentialAuthorizationFailure('invalid_token', status=401)
            if state.get('client_id') not in [None, claims['client_id']] or self.active_configuration(state['configuration'])['scope'] != claims['scope']:
                raise CredentialAuthorizationFailure('invalid_token', status=401)
        elif state.get('original_token_sha256') != identifier or row[1] > claims['exp'] or state['client_id'] != claims['client_id']:
            raise CredentialAuthorizationFailure('invalid_token', status=401)
        return identifier, claims

    def cleanup(self, *, admitted=None):
        if admitted:admitted()
        now = int(time.time())
        removed = 0
        with self.configuration.connect() as connection, connection.cursor() as cursor:
            for table in ['native_authorization', 'native_credential_session', 'native_presentation_recovery', 'native_external_issuance']:
                cursor.execute('DELETE FROM certify.' + table + ' WHERE expires_at<%s', (now,))
                removed += cursor.rowcount
            cursor.execute('DELETE FROM certify.iar_session WHERE expires_at<%s', (datetime.datetime.now(datetime.timezone.utc),))
            removed += cursor.rowcount
            if admitted:admitted()
        return removed
