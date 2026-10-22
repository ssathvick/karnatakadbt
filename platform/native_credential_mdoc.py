"""Native CBOR holder proof and mobile-document issuer-signed structures."""
import base64
import datetime
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Mapping

import cbor2
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from native_certify_authorization import encode
from native_certify_crypto import COSE, sign_bytes, verify_bytes


def decode(value):
    return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)


def cose_public(jwk):
    if jwk.get('kty') != 'EC' or jwk.get('crv') != 'P-256':
        raise ValueError('P-256 document binding key required')
    return {1: 2, -1: 1, -2: decode(jwk['x']), -3: decode(jwk['y'])}


def verify_cwt_holder(proof, nonce, audience, client):
    try:
        compact = proof['cwt']
        if proof.get('proof_type') != 'cwt' or not isinstance(compact, str) or len(compact) > 32768:
            raise ValueError()
        value = cbor2.loads(decode(compact))
        if isinstance(value, cbor2.CBORTag) and value.tag == 61:
            value = value.value
        if isinstance(value, cbor2.CBORTag):
            if value.tag != 18:
                raise ValueError()
            value = value.value
        if not isinstance(value, (tuple, list)) or len(value) != 4:
            raise ValueError()
        protected, unprotected, payload, signature = value
        header = cbor2.loads(protected)
        if not isinstance(header, Mapping) or not isinstance(unprotected, Mapping) or unprotected or header.get(1) != -7 or header.get(3) != 'openid4vci-proof+cwt' or 2 in header or 33 in header:
            raise ValueError()
        key = header['COSE_Key']
        key = cbor2.loads(key) if isinstance(key, bytes) else key
        if not isinstance(key, Mapping) or key.get(1) != 2 or key.get(-1) != 1 or -4 in key or set(key) - {1, 2, 3, 4, -1, -2, -3}:
            raise ValueError()
        if len(key[-2]) != 32 or len(key[-3]) != 32:
            raise ValueError()
        public = ec.EllipticCurvePublicNumbers(int.from_bytes(key[-2], 'big'), int.from_bytes(key[-3], 'big'), ec.SECP256R1()).public_key()
        verify_bytes(public, 'ES256', signature, cbor2.dumps(['Signature1', protected, b'', payload]))
        claims = cbor2.loads(payload)
        if not isinstance(claims, Mapping) or claims.get(3) != audience or claims.get(1) not in [None, client]:
            raise ValueError()
        issued = claims[6]
        if type(issued) not in [int, float] or not time.time() - 300 <= issued <= time.time() + 5 or not isinstance(claims[10], bytes) or not hmac.compare_digest(claims[10], nonce.encode()):
            raise ValueError()
        jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(public))
        canonical = {name: jwk[name] for name in ['crv', 'kty', 'x', 'y']}
        return 'did:jwk:' + encode(json.dumps(canonical, separators=(',', ':')).encode()), canonical
    except Exception:
        raise ValueError('invalid_proof') from None


def issue_mdoc(doctype, namespaces, holder_key, crypto, configuration, now, expiry, *, template=None):
    if template is not None:
        if not isinstance(template, dict) or template.get('docType') != doctype or not isinstance(template.get('nameSpaces'), dict):
            raise ValueError('Invalid document template')
        namespaces = template['nameSpaces']
        validity = template.get('validityInfo', {})
        if not isinstance(validity, dict):
            raise ValueError('Invalid document validity')
        valid_from, valid_until = now, expiry
        for field, placeholder in [('validFrom', '${_validFrom}'), ('validUntil', '${_validUntil}')]:
            value = validity.get(field)
            if value is not None and value != placeholder:
                parsed = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    raise ValueError('Document validity requires a timezone')
                if field == 'validFrom':
                    valid_from = parsed
                else:
                    valid_until = parsed
        if not valid_from < valid_until or valid_until > expiry:
            raise ValueError('Invalid document validity')
    else:
        valid_from, valid_until = now, expiry
    if not isinstance(doctype, str) or not doctype or not isinstance(namespaces, dict) or not namespaces:
        raise ValueError('Namespaced claims required')
    binding = cose_public(holder_key)
    signed_items, value_digests = {}, {}
    for namespace, claims in namespaces.items():
        if not isinstance(namespace, str) or not namespace or not isinstance(claims, list if template is not None else dict) or not claims:
            raise ValueError('Invalid document namespace')
        items, digests = [], {}
        entries = [(item['digestID'], item['elementIdentifier'], item['elementValue']) for item in claims] if template is not None else [(index, name, value) for index, (name, value) in enumerate(claims.items())]
        names = set()
        for index, name, value in entries:
            if type(index) is not int or not 0 <= index < 2**31 or index in digests or name in names:
                raise ValueError('Invalid document digest or duplicate element')
            if not isinstance(name, str) or not name:
                raise ValueError('Invalid document element')
            names.add(name)
            item = cbor2.CBORTag(24, cbor2.dumps({'digestID': index, 'random': secrets.token_bytes(32),
                                              'elementIdentifier': name, 'elementValue': value}))
            items.append(item)
            digests[index] = hashlib.sha256(cbor2.dumps(item)).digest()
        signed_items[namespace], value_digests[namespace] = items, digests
    mso = {'version': '1.0', 'digestAlgorithm': 'SHA-256', 'valueDigests': value_digests,
           'deviceKeyInfo': {'deviceKey': binding}, 'docType': doctype,
           'validityInfo': {'signed': now, 'validFrom': valid_from, 'validUntil': valid_until}}
    payload = cbor2.dumps(cbor2.CBORTag(24, cbor2.dumps(mso, datetime_as_timestamp=False)))
    row, private, certificate = crypto.signing_key({'applicationId': configuration['key_manager_app_id'] or 'CERTIFY_VC_SIGN_EC_R1',
                                                   'referenceId': configuration['key_manager_ref_id'] or ''})
    protected = cbor2.dumps({1: COSE[row['algorithm']]})
    signature = sign_bytes(private, row['algorithm'], cbor2.dumps(['Signature1', protected, b'', payload]))
    issuer_auth = [protected, {33: certificate.public_bytes(serialization.Encoding.DER)}, payload, signature]
    return encode(cbor2.dumps({'docType': doctype, 'issuerSigned': {'nameSpaces': signed_items, 'issuerAuth': issuer_auth}}))
