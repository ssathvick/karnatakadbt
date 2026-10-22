"""Bound, local-only verification of OpenID credential holder proofs."""
import base64
import hashlib
import hmac
import json
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from native_credential_proofs import unbase58


def encode(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def did_key(value):
    """Resolve supported multikeys locally; no DID URLs are fetched."""
    did, separator, fragment = value.partition('#')
    fingerprint = did.removeprefix('did:key:')
    if not did.startswith('did:key:z') or separator and fragment != fingerprint:
        raise ValueError()
    raw = unbase58(fingerprint[1:])
    if raw.startswith(b'\xed\x01') and len(raw) == 34:
        key = ed25519.Ed25519PublicKey.from_public_bytes(raw[2:])
        jwk = json.loads(jwt.algorithms.OKPAlgorithm.to_jwk(key))
    elif raw.startswith(b'\x80\x24') and len(raw) == 35:
        key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw[2:])
        jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key))
    else:
        raise ValueError()
    return did, jwk


def verify_holder(proof, nonce, audience, client):
    try:
        if not isinstance(proof, dict) or proof.get('proof_type') != 'jwt':
            raise ValueError()
        compact = proof['jwt']
        if not isinstance(compact, str) or len(compact) > 16384:
            raise ValueError()
        header = jwt.get_unverified_header(compact)
        if header.get('typ') != 'openid4vci-proof+jwt' or header.get('crit') or any(key in header for key in ['jku', 'x5u', 'x5c']):
            raise ValueError()
        jwk = header.get('jwk')
        holder_did = None
        if isinstance(header.get('kid'), str) and header['kid'].startswith('did:key:'):
            holder_did, resolved = did_key(header['kid'])
            if jwk is not None:
                raise ValueError()
            jwk = resolved
        if jwk is None and isinstance(header.get('kid'), str) and header['kid'].startswith('did:jwk:'):
            encoded = header['kid'].split('#')[0].removeprefix('did:jwk:')
            jwk = json.loads(base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True))
        if not isinstance(jwk, dict) or any(key in jwk for key in ['d', 'p', 'q', 'dp', 'dq', 'qi', 'oth', 'k']):
            raise ValueError()
        algorithm, fields = {'RSA': ('RS256', ['e', 'kty', 'n']), 'EC': ('ES256', ['crv', 'kty', 'x', 'y']),
                             'OKP': ('EdDSA', ['crv', 'kty', 'x'])}[jwk['kty']]
        if header.get('alg') != algorithm or jwk.get('kty') == 'EC' and jwk.get('crv') != 'P-256' or jwk.get('kty') == 'OKP' and jwk.get('crv') != 'Ed25519':
            raise ValueError()
        public = jwt.PyJWK.from_dict(jwk, algorithm=algorithm).key
        if jwk['kty'] == 'RSA' and public.key_size < 2048:
            raise ValueError()
        claims = jwt.decode(compact, public, algorithms=[algorithm], audience=audience,
                            options={'require': ['aud', 'iat', 'nonce']})
        if claims.get('iss') not in [None, client] or not isinstance(claims['nonce'], str) or not hmac.compare_digest(claims['nonce'], nonce):
            raise ValueError()
        if type(claims['iat']) not in [int, float] or not time.time() - 300 <= claims['iat'] <= time.time() + 5:
            raise ValueError()
        canonical = {key: jwk[key] for key in sorted(fields)}
        holder = holder_did or 'did:jwk:' + encode(json.dumps(canonical, separators=(',', ':')).encode())
        return holder, canonical
    except (ValueError, TypeError, KeyError, jwt.PyJWTError):
        raise ValueError('invalid_proof') from None
