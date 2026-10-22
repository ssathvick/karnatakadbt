"""Native wallet enrolment using the configured synthetic identity authority.

Enrolment verifies an identity proof before certifying a public key. Identity
secrets and private wallet keys are never persisted by this component.
"""
import datetime
import hashlib
import hmac
import json
import secrets
from urllib.parse import quote

import httpx
import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID
from jwcrypto import jwk, jwe

from native_auth_cache import AuthenticationFailure, b64, canonical, sha
from native_auth_clients import public_keys


class WalletBinding:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings

    def context(self):
        return {'relyingPartyId': self.settings['relying_party'], 'clientId': self.settings['client']}

    def send_otp(self, value):
        individual = value.get('individualId')
        if not isinstance(individual, str) or not 1 <= len(individual) <= 8192:
            raise AuthenticationFailure('invalid_individual_id')
        channels = value.get('otpChannels')
        if not isinstance(channels, list) or not channels or set(channels) - {'email', 'phone', 'mobile'}:
            raise AuthenticationFailure('invalid_otp_channel')
        self.engine.rate(individual, 'binding-otp')
        # Retained wrapper uses this exact, identity-scoped transaction name.
        # It permits a pending OTP to continue through an original-binary rollback.
        result = self.engine.identity('send-otp', self.context(),
                                      {'individualId': individual, 'transactionId': 'MockTransaction', 'otpChannels': channels})
        return {'maskedEmail': result.get('maskedEmail'), 'maskedMobile': result.get('maskedMobile')}

    def bind(self, value):
        individual = value.get('individualId')
        if not isinstance(individual, str) or not 1 <= len(individual) <= 8192:
            raise AuthenticationFailure('invalid_individual_id')
        if value.get('authFactorType') != 'WLA' or value.get('format') != 'jwt':
            raise AuthenticationFailure('invalid_bind_auth_factor_type')
        keys = public_keys(value.get('publicKey'))
        if len(keys) != 1:
            raise AuthenticationFailure('invalid_public_key')
        public = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(keys[0]))
        challenges = value.get('challengeList')
        if not isinstance(challenges, list) or not 1 <= len(challenges) <= 5:
            raise AuthenticationFailure('invalid_auth_challenge')
        mapping = {'PIN': ('pin', 'number'), 'OTP': ('otp', 'alpha-numeric'), 'BIO': ('biometrics', 'encoded-json')}
        proof = {'individualId': individual, 'transactionId': 'MockTransaction'}
        for challenge in challenges:
            if not isinstance(challenge, dict) or challenge.get('authFactorType') not in mapping:
                raise AuthenticationFailure('invalid_auth_factor_type_or_challenge_format')
            name, format_name = mapping[challenge['authFactorType']]
            if challenge.get('format') != format_name or name in proof or not isinstance(challenge.get('challenge'), str):
                raise AuthenticationFailure('invalid_auth_factor_type_or_challenge_format')
            proof[name] = challenge['challenge']
        self.engine.rate(individual, 'binding')
        result = self.engine.identity('kyc-auth', self.context(), proof)
        if result.get('authStatus') is not True:
            raise AuthenticationFailure('auth_failed')
        # Consume the identity exchange created by enrolment; do not leave a
        # reusable KYC capability behind a completed binding operation.
        request = {'individualId': individual, 'transactionId': 'MockTransaction', 'kycToken': result['kycToken'],
                   'requestDateTime': datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z'),
                   'acceptedClaims': [], 'claimLocales': []}
        self.engine.identity('kyc-exchange', self.context(), request)
        self.engine.signing.ensure_wallet_issuer()
        alias, issuer_key, issuer_cert = self.engine.signing.key('MOCK_BINDING_SERVICE')
        now = datetime.datetime.now(datetime.timezone.utc)
        expires = min(now + datetime.timedelta(days=self.settings.get('validity_days', 10)), issuer_cert.not_valid_after_utc)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'KarnatakaDBT Wallet')])
        certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer_cert.subject)
                       .public_key(public).serial_number(x509.random_serial_number())
                       .not_valid_before(now - datetime.timedelta(seconds=30)).not_valid_after(expires)
                       .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                       .sign(issuer_key, hashes.SHA256()))
        cert = certificate.public_bytes(serialization.Encoding.PEM).decode()
        thumbprint = b64(certificate.fingerprint(hashes.SHA256()))
        encoded = canonical(keys[0]).decode()
        public_hash = sha(encoded)
        material = sha(keys[0]['n'] + ':' + keys[0]['e'])
        identity_hash = sha(individual)
        with self.engine.clients.connect() as connection, connection.cursor() as cursor:
            # Serialize both key reuse checks and replacement of this subject's
            # binding so simultaneous requests cannot bind one key to two users.
            for lock in sorted(['wallet-key:' + material, 'wallet-subject:' + identity_hash]):
                cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (lock,))
            cursor.execute('SELECT id_hash,public_key,wallet_binding_id FROM esignet.public_key_registry')
            binding = None
            for old_hash, old_key, old_binding in cursor.fetchall():
                old = json.loads(old_key)
                if old_hash != identity_hash and old.get('n') == keys[0]['n'] and old.get('e') == keys[0]['e']:
                    raise AuthenticationFailure('duplicate_public_key')
                if old_hash == identity_hash:
                    binding = old_binding
            binding = binding or b64(hashlib.sha3_256(individual.encode() + secrets.token_bytes(16)).digest())
            cursor.execute('''INSERT INTO esignet.public_key_registry
                (id_hash,auth_factor,psu_token,public_key,expire_dtimes,wallet_binding_id,public_key_hash,certificate,cr_dtimes,thumbprint)
                VALUES(%s,'WLA',%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(id_hash,auth_factor) DO UPDATE SET
                psu_token=EXCLUDED.psu_token,public_key=EXCLUDED.public_key,expire_dtimes=EXCLUDED.expire_dtimes,
                public_key_hash=EXCLUDED.public_key_hash,certificate=EXCLUDED.certificate,
                cr_dtimes=EXCLUDED.cr_dtimes,thumbprint=EXCLUDED.thumbprint''',
                (identity_hash, individual, encoded, expires.replace(tzinfo=None), binding, public_hash,
                 cert, now.replace(tzinfo=None), thumbprint))
        wallet_id = binding
        if self.settings.get('encrypt_binding_id'):
            encrypted = jwe.JWE(binding.encode(), protected={'alg': 'RSA-OAEP-256', 'enc': 'A256GCM', 'cty': 'JWT',
                                                            **({'kid': keys[0]['kid']} if keys[0].get('kid') else {})})
            encrypted.add_recipient(jwk.JWK(**keys[0]))
            wallet_id = encrypted.serialize(compact=True)
        return {'walletUserId': wallet_id, 'certificate': cert,
                'expireDateTime': expires.isoformat(timespec='milliseconds').replace('+00:00', 'Z')}

    def validate_challenge(self, individual, token, transaction):
        """Verify retained WLA claims; identity authority independently rechecks."""
        from native_auth_wallet_proof import verify_wallet_token, WalletProofFailure
        try:
            verify_wallet_token(self.engine.clients.connection, individual, token,
                                audience=self.settings.get('audience', 'esignet-binding'))
        except WalletProofFailure:
            raise AuthenticationFailure('invalid_wla_token') from None
        return {'tokens': [token]}
