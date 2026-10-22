"""Native multi-algorithm Certify signatures, COSE and CWT wire operations."""
import base64
import datetime
import hashlib
import json
import time
import uuid
from collections.abc import Mapping

import cbor2
import jwt
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519, padding, utils

from native_keymanager import VaultFailure, certificate, stamp
from native_keymanager_jose import unbase
from native_key_vault import canonical, encode


COSE = {'RS256': -257, 'RS384': -258, 'RS512': -259, 'PS256': -37, 'PS384': -38,
        'PS512': -39, 'ES256': -7, 'ES256K': -47, 'ES384': -35, 'ES512': -36, 'EdDSA': -8}


def digest(algorithm):
    return {'256': hashes.SHA256(), '384': hashes.SHA384(), '512': hashes.SHA512()}[
        '256' if algorithm == 'ES256K' else algorithm[-3:]]


def sign_bytes(key, algorithm, data):
    if algorithm not in COSE:
        raise VaultFailure('Unsupported signature algorithm')
    if algorithm.startswith(('RS', 'PS')):
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            raise VaultFailure('RSA key required')
        hash_algorithm = digest(algorithm)
        scheme = padding.PKCS1v15() if algorithm.startswith('RS') else padding.PSS(
            mgf=padding.MGF1(hash_algorithm), salt_length=hash_algorithm.digest_size)
        return key.sign(data, scheme, hash_algorithm)
    if algorithm.startswith('ES'):
        curves = {'ES256': 'secp256r1', 'ES256K': 'secp256k1', 'ES384': 'secp384r1', 'ES512': 'secp521r1'}
        if not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != curves[algorithm]:
            raise VaultFailure('EC key and algorithm mismatch')
        r, s = utils.decode_dss_signature(key.sign(data, ec.ECDSA(digest(algorithm))))
        width = (key.key_size + 7) // 8
        return r.to_bytes(width, 'big') + s.to_bytes(width, 'big')
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise VaultFailure('Ed25519 key required')
    return key.sign(data)


def verify_bytes(key, algorithm, signature, data):
    if algorithm not in COSE:
        raise VaultFailure('Unsupported signature algorithm')
    if algorithm.startswith(('RS', 'PS')):
        if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 2048:
            raise VaultFailure('RSA key required')
        hash_algorithm = digest(algorithm)
        scheme = padding.PKCS1v15() if algorithm.startswith('RS') else padding.PSS(
            mgf=padding.MGF1(hash_algorithm), salt_length=hash_algorithm.digest_size)
        key.verify(signature, data, scheme, hash_algorithm)
    elif algorithm.startswith('ES'):
        curves = {'ES256': 'secp256r1', 'ES256K': 'secp256k1', 'ES384': 'secp384r1', 'ES512': 'secp521r1'}
        if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != curves[algorithm]:
            raise VaultFailure('EC key and algorithm mismatch')
        width = (key.key_size + 7) // 8
        if len(signature) != width * 2:
            raise VaultFailure('Invalid ECDSA signature length')
        der = utils.encode_dss_signature(int.from_bytes(signature[:width], 'big'), int.from_bytes(signature[width:], 'big'))
        key.verify(der, data, ec.ECDSA(digest(algorithm)))
    else:
        if not isinstance(key, ed25519.Ed25519PublicKey):
            raise VaultFailure('Ed25519 key required')
        key.verify(signature, data)


def multibase58(value):
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    number, text = int.from_bytes(value, 'big'), ''
    while number:
        number, digit = divmod(number, 58)
        text = alphabet[digit] + text
    zeros = len(value) - len(value.lstrip(b'\0'))
    return 'z' + '1' * zeros + text


class CertifyCrypto:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings

    def scope(self, request):
        app = request.get('applicationId') or self.settings['default_application']
        ref = request.get('referenceId') or (self.settings['default_reference'] if not request.get('applicationId') else '')
        self.engine.policy(app, ref)
        return app, ref

    def signing_key(self, request):
        app, ref = self.scope(request)
        with self.engine.vault.connect() as connection:
            row = self.engine._row(connection, app, ref)
            cert = certificate(row['certificate'])
            self.engine._valid(cert)
            return row, self.engine.vault._private(row), cert

    def certificates(self, request):
        app, ref = self.scope(request)
        with self.engine.vault.connect() as connection:
            rows = connection.execute('''SELECT k.*,t.certificate FROM vault_keys k
                JOIN km_certificates t ON k.id=t.key_id WHERE k.application=? AND k.reference=?''', (app, ref)).fetchall()
        return [dict(row) for row in rows]

    def verification_certificate(self, request, header=None):
        header = header or {}
        rows = self.certificates(request)
        supplied = request.get('certificateData')
        if supplied:
            cert = certificate(supplied)
        elif header.get('x5c'):
            if not isinstance(header['x5c'], list) or not 1 <= len(header['x5c']) <= 10:
                raise VaultFailure('Invalid certificate chain')
            cert = x509.load_der_x509_certificate(unbase(header['x5c'][0]))
        else:
            matched = [row for row in rows if row['state'] != 'REVOKED' and
                       (self.engine.jose_id(row) == header.get('kid') or row['id'] == header.get('kid'))]
            if not header.get('kid'):
                matched = [row for row in rows if row['state'] == 'ACTIVE']
            if len(matched) != 1:
                raise VaultFailure('Certificate is not registered in the requested scope')
            cert = certificate(matched[0]['certificate'])
        self.engine._valid(cert)
        if any(row['state'] == 'REVOKED' and certificate(row['certificate']).fingerprint(hashes.SHA256()) == cert.fingerprint(hashes.SHA256()) for row in rows):
            raise VaultFailure('Certificate has been revoked')
        return cert

    def trust(self, request, cert):
        if request.get('validateTrust') is not True:
            return 'Trust Not Verified'
        valid = self.engine.trust({'partnerDomain': request.get('domain'),
                                  'certificateData': cert.public_bytes(serialization.Encoding.PEM).decode()})['status']
        return 'Trust Valid' if valid else 'Trust Not Valid'

    def jws_sign(self, request, *, jws=False):
        row, key, cert = self.signing_key(request)
        payload = unbase(request['dataToSign'])
        if not jws or request.get('validateJson'):
            json.loads(payload)
        algorithm = request.get('signAlgorithm') or row['algorithm']
        header = {'alg': algorithm, 'kid': self.engine.jose_id(row)}
        additions = request.get('additionalHeaders') or {}
        if not isinstance(additions, dict) or set(additions) & {'alg', 'kid', 'crit', 'b64', 'jku', 'x5u', 'x5c', 'x5t#S256'}:
            raise VaultFailure('Reserved signature header')
        header.update(additions)
        if request.get('includeCertificate') or request.get('includeCertificateChain'):
            header['x5c'] = [base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()]
        if request.get('includeCertHash'):
            header['x5t#S256'] = encode(cert.fingerprint(hashes.SHA256()))
        if request.get('certificateUrl'):
            if not request['certificateUrl'].startswith('https://'):
                raise VaultFailure('HTTPS certificate metadata URL required')
            header['x5u'] = request['certificateUrl']
        encoded = request.get('b64JWSHeaderParam', True) if jws else True
        if type(encoded) is not bool:
            raise VaultFailure('Boolean payload encoding flag required')
        if not encoded:
            header.update(b64=False, crit=['b64'])
        head = encode(canonical(header))
        body = encode(payload) if encoded else payload.decode()
        if not encoded and request.get('includePayload') and '.' in body:
            raise VaultFailure('Unencoded compact payload contains a delimiter')
        signature = sign_bytes(key, algorithm, (head + '.' + body).encode())
        return {'jwtSignedData': head + '.' + (body if request.get('includePayload') else '') + '.' + encode(signature),
                'timestamp': stamp(self.engine.clock())}

    def jws_verify(self, request):
        head, body, signature = request['jwtSignatureData'].split('.')
        header = json.loads(unbase(head))
        if header.get('crit') not in [None, [], ['b64']] or header.get('b64', True) not in [True, False]:
            raise VaultFailure('Unsupported critical header')
        if header.get('b64') is False and header.get('crit') != ['b64']:
            raise VaultFailure('Unencoded payload must be marked critical')
        if request.get('actualData') is not None:
            if body:
                raise VaultFailure('Detached payload cannot override an included payload')
            raw = request['actualData'].encode()
            body = encode(raw) if header.get('b64', True) else raw.decode()
        cert = self.verification_certificate(request, header)
        valid = True
        try:
            verify_bytes(cert.public_key(), header['alg'], unbase(signature), (head + '.' + body).encode())
        except InvalidSignature:
            valid = False
        return {'signatureValid': valid, 'message': 'Validation Successful' if valid else 'Validation Failed',
                'trustValid': self.trust(request, cert)}

    def raw_sign(self, request, *, detailed=False):
        row, key, cert = self.signing_key(request)
        algorithm = request.get('signAlgorithm') or row['algorithm']
        signature = sign_bytes(key, algorithm, unbase(request['dataToSign']))
        encoding = request.get('responseEncodingFormat') or 'base58btc'
        if encoding not in ['base58btc', 'base64url']:
            raise VaultFailure('Unsupported signature encoding')
        value = multibase58(signature) if encoding == 'base58btc' else encode(signature)
        result = {'signature': value, 'timestamp': stamp(self.engine.clock())}
        if detailed:
            result = {'signedData': value, 'keyId': self.engine.jose_id(row),
                      'certificate': cert.public_bytes(serialization.Encoding.PEM).decode(),
                      'signatureAlgorithm': algorithm, 'timestamp': result['timestamp']}
        return result

    def cose_sign(self, request, *, cwt=False):
        row, key, cert = self.signing_key(request)
        algorithm = request.get('algorithm') or row['algorithm']
        if cwt:
            claims = json.loads(unbase(request['payload'])) if request.get('payload') else {}
            if not isinstance(claims, dict):
                raise VaultFailure('CWT claims must be a map')
            claims = {int(k) if str(k).lstrip('-').isdigit() else k: v for k, v in claims.items()}
            now = int(time.time())
            nbf, expires = request.get('notBeforeDays', 0), request.get('expireDays', 365)
            if type(nbf) is not int or type(expires) is not int or not 0 <= nbf <= 36500 or not 0 <= expires <= 36500:
                raise VaultFailure('Bounded nonnegative validity days required')
            claims.update({4: now + (nbf + expires) * 86400, 5: now + nbf * 86400, 6: now})
            for name, label in [('issuer', 1), ('subject', 2), ('audience', 3)]:
                if request.get(name):
                    claims[label] = request[name]
            if request.get('cwtid'):
                claims[7] = (str(uuid.uuid4()) if request['cwtid'].upper() == 'UUID' else request['cwtid']).encode()
            if request.get('claim169Payload'):
                claims[169] = cbor2.loads(bytes.fromhex(request['claim169Payload']))
            payload = cbor2.dumps(claims)
        else:
            payload = unbase(request['payload'])
        protected = {1: COSE[algorithm]}
        unprotected = {33: cert.public_bytes(serialization.Encoding.DER)}
        names = {'alg': 1, 'content_type': 3, 'kid': 4, 'x5chain': 33}
        for field, target in [('protectedHeader', protected), ('unprotectedHeader', unprotected)]:
            for name, value in (request.get(field) or {}).items():
                if name in ['kid', 'x5c'] and type(value) is bool:
                    if not value:
                        continue
                    label = 4 if name == 'kid' else 33
                    target[label] = self.engine.jose_id(row).encode() if name == 'kid' else cert.public_bytes(serialization.Encoding.DER)
                    if field == 'protectedHeader':
                        unprotected.pop(label, None)
                    continue
                label = int(name) if str(name).lstrip('-').isdigit() else names.get(name, name)
                if label in [1, 33]:
                    if label == 1 and value in [algorithm, COSE[algorithm]]:
                        continue
                    raise VaultFailure('Reserved COSE header')
                if label == 4 and isinstance(value, str):
                    value = value.encode()
                target[label] = value
        if set(protected) & set(unprotected):
            raise VaultFailure('COSE header labels overlap')
        encoded_header = cbor2.dumps(protected)
        data = cbor2.dumps(['Signature1', encoded_header, b'', payload])
        signature = sign_bytes(key, algorithm, data)
        message = [encoded_header, unprotected, payload, signature]
        if request.get('includeCOSETag') or cwt:
            message = cbor2.CBORTag(18, message)
        if cwt:
            message = cbor2.CBORTag(61, message)
        return {'signedData': cbor2.dumps(message).hex(), 'timestamp': stamp(self.engine.clock())}

    def cose_verify(self, request, *, cwt=False):
        raw = request['coseSignedData']
        if not isinstance(raw, str) or len(raw) > 2 * 1024 * 1024:
            raise VaultFailure('Bounded COSE data required')
        message = cbor2.loads(bytes.fromhex(raw))
        tags = []
        while isinstance(message, cbor2.CBORTag):
            tags.append(message.tag)
            message = message.value
        if any(tag not in [18, 61] for tag in tags) or len(tags) > 2 or not isinstance(message, (list, tuple)) or len(message) != 4:
            raise VaultFailure('Invalid COSE Sign1 structure')
        protected, unprotected, payload, signature = message
        if not isinstance(protected, bytes) or not isinstance(unprotected, Mapping) or not isinstance(payload, bytes) or not isinstance(signature, bytes):
            raise VaultFailure('Invalid COSE Sign1 field types')
        decoded = cbor2.loads(protected)
        if not isinstance(decoded, dict) or set(decoded) & set(unprotected) or decoded.get(2):
            raise VaultFailure('Unsupported COSE headers')
        algorithm = next((name for name, code in COSE.items() if code == decoded.get(1)), None)
        if algorithm is None:
            raise VaultFailure('Unsupported COSE algorithm')
        header = {**unprotected, **decoded}
        certificate_bytes = header.get(33)
        if isinstance(certificate_bytes, (list, tuple)):
            certificate_bytes = certificate_bytes[0]
        metadata = {}
        if certificate_bytes:
            metadata['x5c'] = [base64.b64encode(certificate_bytes).decode()]
        if header.get(4):
            metadata['kid'] = header[4].decode() if isinstance(header[4], bytes) else header[4]
        cert = self.verification_certificate(request, metadata)
        valid = True
        try:
            verify_bytes(cert.public_key(), algorithm, signature,
                         cbor2.dumps(['Signature1', protected, b'', payload]))
        except InvalidSignature:
            valid = False
        if cwt and valid:
            claims = cbor2.loads(payload)
            now = time.time()
            if not isinstance(claims, dict):
                raise VaultFailure('CWT claims must be a map')
            if not all(k in claims and isinstance(claims[k], (int, float)) and not isinstance(claims[k], bool) for k in [4, 5, 6]) or claims[4] <= now or claims[5] > now:
                valid = False
            for name, label in [('issuer', 1), ('subject', 2)]:
                if request.get(name) is not None and claims.get(label) != request[name]:
                    valid = False
        return {'signatureValid': valid, 'message': 'Validation Successful' if valid else 'Validation Failed',
                'trustValid': self.trust(request, cert)}
