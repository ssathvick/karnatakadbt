"""Linked-data proofs using pinned JSON-LD contexts and standard RSA primitives."""
import base64
import copy
import datetime
import hashlib
import json
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa, ec, ed25519, utils
from pyld import jsonld


class CredentialProofFailure(ValueError):
    pass


SUITE_CONTEXTS = {
    'Ed25519Signature2018': 'https://w3id.org/security/suites/ed25519-2018/v1',
    'Ed25519Signature2020': 'https://w3id.org/security/suites/ed25519-2020/v1',
    'EcdsaSecp256k1Signature2019': 'https://w3id.org/security/suites/secp256k1-2019/v1',
    'JsonWebSignature2020': 'https://w3id.org/security/suites/jws-2020/v1',
}
INTEGRITY_SUITES = {'ecdsa-rdfc-2019': 'ES256K', 'ecdsa-jcs-2019': 'ES256K',
                    'eddsa-rdfc-2022': 'EdDSA', 'eddsa-jcs-2022': 'EdDSA'}
INTEGRITY_CONTEXT = 'https://w3id.org/security/data-integrity/v2'


def base58(value):
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    number, result = int.from_bytes(value, 'big'), ''
    while number:
        number, digit = divmod(number, 58)
        result = alphabet[digit] + result
    return '1' * (len(value) - len(value.lstrip(b'\0'))) + result


def unbase58(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        raise ValueError()
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    number = 0
    for character in value:
        number = number * 58 + alphabet.index(character)
    return b'\0' * (len(value) - len(value.lstrip('1'))) + number.to_bytes((number.bit_length() + 7) // 8, 'big')


def algorithm(key, suite):
    if suite in INTEGRITY_SUITES:
        selected = INTEGRITY_SUITES[suite]
        if selected == 'EdDSA' and isinstance(key, (ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey)):
            return selected
        if selected == 'ES256K' and isinstance(key, (ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey)) and key.curve.name == 'secp256k1':
            return selected
        raise CredentialProofFailure('unsupported_signature_suite_or_key')
    if isinstance(key, (rsa.RSAPrivateKey, rsa.RSAPublicKey)) and key.key_size >= 2048 and suite in ['RsaSignature2018', 'JsonWebSignature2020']:
        return 'RS256'
    if isinstance(key, (ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey)) and suite in ['Ed25519Signature2018', 'Ed25519Signature2020', 'JsonWebSignature2020']:
        return 'EdDSA'
    if isinstance(key, (ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey)):
        if key.curve.name == 'secp256k1' and suite in ['EcdsaKoblitzSignature2016', 'EcdsaSecp256k1Signature2019', 'JsonWebSignature2020']:
            return 'ES256K'
        if key.curve.name == 'secp256r1' and suite in ['EcdsaSecp256r1Signature2019', 'JsonWebSignature2020']:
            return 'ES256'
    raise CredentialProofFailure('unsupported_signature_suite_or_key')


def signature(key, alg, data):
    if alg == 'RS256':
        return key.sign(data, padding.PKCS1v15(), hashes.SHA256())
    if alg == 'EdDSA':
        return key.sign(data)
    r, s = utils.decode_dss_signature(key.sign(data, ec.ECDSA(hashes.SHA256())))
    return r.to_bytes(32, 'big') + s.to_bytes(32, 'big')


def verify_signature(key, alg, value, data):
    if alg == 'RS256':
        key.verify(value, data, padding.PKCS1v15(), hashes.SHA256())
    elif alg == 'EdDSA':
        key.verify(value, data)
    else:
        if len(value) != 64:
            raise ValueError()
        key.verify(utils.encode_dss_signature(int.from_bytes(value[:32], 'big'), int.from_bytes(value[32:], 'big')),
                   data, ec.ECDSA(hashes.SHA256()))


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def unb64(value):
    return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


class LinkedDataProofs:
    def __init__(self, catalog, runtime=None):
        self.contexts = json.loads(Path(catalog).read_text())
        self.catalog, self.runtime = str(Path(catalog).resolve()), Path(runtime).resolve() if runtime else None

    def loader(self, url, options=None):
        if url not in self.contexts:
            raise CredentialProofFailure('untrusted_credential_context')
        return {'contextUrl': None, 'documentUrl': url, 'document': copy.deepcopy(self.contexts[url])}

    def normalize(self, document):
        try:
            result = jsonld.normalize(document, {'algorithm': 'URDNA2015', 'format': 'application/n-quads',
                                                  'documentLoader': self.loader})
            if not result:
                raise ValueError()
            return result.encode()
        except Exception:
            raise CredentialProofFailure('invalid_credential_document') from None

    def verify_data(self, document, proof):
        if proof.get('type') == 'DataIntegrityProof':
            try:
                if proof.get('cryptosuite') not in INTEGRITY_SUITES or self.runtime is None:
                    raise ValueError()
                classpath = str(self.runtime / 'classes') + ':' + ':'.join(str(path) for path in sorted((self.runtime / 'lib').glob('*.jar')))
                raw = canonical({'suite': proof['cryptosuite'], 'document': document, 'proof': proof})
                if len(raw) > 1024 * 1024:
                    raise ValueError()
                result = subprocess.run([str(self.runtime / 'jre/bin/java'), '-Xmx96m', '-Xss256k', '-cp', classpath,
                                         'NativeCredentialCanonicalizer', self.catalog], input=raw,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
                if result.returncode or len(result.stdout) > 128:
                    raise ValueError()
                data = base64.b64decode(result.stdout, validate=True)
                if len(data) != 64:
                    raise ValueError()
                return data
            except (ValueError, OSError, subprocess.SubprocessError):
                raise CredentialProofFailure('invalid_integrity_canonicalization') from None
        unsigned = copy.deepcopy(document)
        unsigned.pop('proof', None)
        options = {k: copy.deepcopy(v) for k, v in proof.items() if k not in ['jws', 'proofValue', 'signatureValue']}
        # The retained signing suites normalize proof options using the
        # security proof context independently of the credential's claim
        # vocabulary. Inheriting a custom @vocab can change security IRIs.
        options['@context'] = ['https://w3id.org/security/v2']
        if proof.get('type') in SUITE_CONTEXTS:
            options['@context'].append(SUITE_CONTEXTS[proof['type']])
        return hashlib.sha256(self.normalize(options)).digest() + hashlib.sha256(self.normalize(unsigned)).digest()

    def sign(self, document, private_key, verification_method, *, created=None, suite='RsaSignature2018'):
        if 'proof' in document or len(canonical(document)) > 1024 * 1024:
            raise CredentialProofFailure('invalid_credential_document')
        created = created or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        document = copy.deepcopy(document)
        definitions = [self.contexts[value].get('@context', {}) if isinstance(value, str) and value in self.contexts else value
                       for value in document['@context']]
        already_defined = any(isinstance(value, dict) and suite in value for value in definitions)
        if suite in SUITE_CONTEXTS and SUITE_CONTEXTS[suite] not in document['@context'] and not already_defined:
            document['@context'].append(SUITE_CONTEXTS[suite])
        alg = algorithm(private_key, suite)
        proof = {'type': suite, 'created': created,
                 'verificationMethod': verification_method, 'proofPurpose': 'assertionMethod'}
        if suite in INTEGRITY_SUITES:
            if INTEGRITY_CONTEXT not in document['@context']:
                document['@context'].append(INTEGRITY_CONTEXT)
            proof.update(type='DataIntegrityProof', cryptosuite=suite)
            proof['@context'] = [INTEGRITY_CONTEXT]
        data = self.verify_data(document, proof)
        if suite in ['Ed25519Signature2020', 'EcdsaSecp256r1Signature2019'] or suite in INTEGRITY_SUITES:
            proof['proofValue'] = 'z' + base58(signature(private_key, alg, data))
        else:
            header = b64(canonical({'alg': alg, 'b64': False, 'crit': ['b64']}))
            signed = signature(private_key, alg, header.encode() + b'.' + data)
            proof['jws'] = header + '..' + b64(signed)
        return {**copy.deepcopy(document), 'proof': proof}

    def verify(self, document, public_key, verification_method):
        try:
            proof = document['proof']
            suite = proof.get('type')
            if suite == 'DataIntegrityProof':
                suite = proof.get('cryptosuite')
            alg = algorithm(public_key, suite)
            if proof.get('proofPurpose') != 'assertionMethod' or proof.get('verificationMethod') != verification_method:
                raise ValueError()
            if suite in ['Ed25519Signature2020', 'EcdsaSecp256r1Signature2019'] or suite in INTEGRITY_SUITES:
                if not proof['proofValue'].startswith('z') or 'jws' in proof:
                    raise ValueError()
                verify_signature(public_key, alg, unbase58(proof['proofValue'][1:]), self.verify_data(document, proof))
            else:
                header, detached, signed = proof['jws'].split('.')
                parameters = json.loads(unb64(header))
                if not isinstance(parameters, dict) or parameters.get('alg') != alg or parameters.get('b64') is not False or parameters.get('crit') != ['b64']:
                    raise ValueError()
                # Retained signers include signed key identifiers and certificate
                # thumbprints. Verification still uses the caller's pinned key;
                # these fields never select a network resource or another key.
                if set(parameters) - {'alg', 'b64', 'crit', 'kid', 'x5t#S256', 'x5t'}:
                    raise ValueError()
                for name in ['kid', 'x5t#S256', 'x5t']:
                    if name in parameters and (not isinstance(parameters[name], str) or not 1 <= len(parameters[name]) <= 256):
                        raise ValueError()
                if 'kid' in parameters and parameters['kid'] != verification_method.rsplit('#', 1)[-1]:
                    raise ValueError()
                if detached or 'proofValue' in proof:
                    raise ValueError()
                verify_signature(public_key, alg, unb64(signed), header.encode() + b'.' + self.verify_data(document, proof))
            return True
        except Exception:
            raise CredentialProofFailure('invalid_credential_proof') from None
