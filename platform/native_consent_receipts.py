"""Persistent asymmetric consent receipts with original canonical wire format."""
import base64
import hashlib
import json
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519, padding
from jwt.algorithms import RSAAlgorithm, ECAlgorithm, OKPAlgorithm


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str).encode()


class NativeConsentReceipts:
    def __init__(self, private_key, kid):
        if not kid:
            raise ValueError('Persistent signing key identifier required')
        if isinstance(private_key, rsa.RSAPrivateKey) and private_key.key_size >= 2048:
            self.algorithm, self.jwk_algorithm = 'RS256', RSAAlgorithm
        elif isinstance(private_key, ec.EllipticCurvePrivateKey) and isinstance(private_key.curve, ec.SECP256R1):
            self.algorithm, self.jwk_algorithm = 'ES256', ECAlgorithm
        elif isinstance(private_key, ed25519.Ed25519PrivateKey):
            self.algorithm, self.jwk_algorithm = 'EdDSA', OKPAlgorithm
        else:
            raise ValueError('Supported persistent asymmetric signing key required')
        self.key, self.kid = private_key, kid

    def jwks(self):
        key = json.loads(self.jwk_algorithm.to_jwk(self.key.public_key()))
        return {'keys': [{**key, 'kid': self.kid, 'alg': self.algorithm, 'use': 'sig'}]}

    def build(self, artefact, partner):
        document = {'@context': 'https://openg2p.org/contexts/consent_artefact.jsonld', '@type': 'ConsentArtefact',
                    'consent_id': artefact['id'], 'subject_id': artefact['subject_id_value'],
                    'subject_id_type': artefact['subject_id_type'], 'data_controller': artefact['controller_id'],
                    'partner_id': artefact['partner_id'], 'source': artefact['source'], 'purpose': artefact['purpose'],
                    'data_scopes': artefact['data_scopes'], 'effective_data_scopes': artefact['effective_data_scopes'],
                    'fetch_type': artefact['fetch_type'], 'policy_version': artefact['policy_version'],
                    'validity': {'consent_timestamp': artefact['valid_from'].isoformat(), 'expiry_timestamp': artefact['valid_until'].isoformat()}}
        digest = 'sha256:' + hashlib.sha256(canonical(document)).hexdigest()
        if self.algorithm == 'RS256':
            signed = self.key.sign(digest.encode(), padding.PKCS1v15(), hashes.SHA256())
        elif self.algorithm == 'ES256':
            # Historical receipt protocol uses DER ECDSA, not compact-JWS r||s.
            signed = self.key.sign(digest.encode(), ec.ECDSA(hashes.SHA256()))
        else:
            signed = self.key.sign(digest.encode())
        signature = base64.urlsafe_b64encode(signed).rstrip(b'=').decode()
        receipt = {'@context': 'https://openg2p.org/contexts/consent_receipt.jsonld', '@type': 'ConsentReceipt', 'version': '1.1',
                   'issued_at': artefact['created_at'].isoformat(), 'data_controller': {'id': artefact['controller_id']},
                   'subject_id': artefact['subject_id_value'],
                   'purposes': [{**(artefact['purpose'] or {}), 'legal_basis': 'consent', 'data_categories': artefact['effective_data_scopes']}],
                   'data_categories': artefact['effective_data_scopes'], 'third_parties': [partner['audience']],
                   'withdrawal': {'method': 'POST /consent/v1/consents/' + artefact['id'] + '/revoke'},
                   'consent_artefact': {'@id': artefact['id'], 'hash': digest},
                   'signature': {'algorithm': self.algorithm, 'kid': self.kid, 'value': signature}}
        return dict(consent_id=artefact['id'], artefact_hash=digest, algorithm=self.algorithm, kid=self.kid,
                    signature=signature, version='1.1', document=receipt)
