"""Pinned OIDC identity exchange; endpoints and trust come from issuer settings."""
import json
import ssl
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import jwt
from jwcrypto import jwk, jwe
from jwcrypto.common import JWException


def verify(compact, keys, **options):
    if not isinstance(compact, str) or not 0 < len(compact) <= 512 * 1024:
        raise ValueError('Invalid identity assertion')
    header = jwt.get_unverified_header(compact)
    if header.get('alg') != 'RS256' or header.get('crit') or any(k in header for k in ['jku', 'x5u', 'jwk', 'x5c']):
        raise ValueError('Untrusted assertion key')
    if not isinstance(keys, list) or not 1 <= len(keys) <= 16:
        raise ValueError('Pinned public keys required')
    matches = []
    for public in keys:
        if not isinstance(public, dict) or any(k in public for k in ['d', 'p', 'q', 'dp', 'dq', 'qi', 'oth', 'k']):
            raise ValueError('Only public trust keys allowed')
        if header.get('kid') is not None and header['kid'] != public.get('kid'):
            continue
        key = jwt.PyJWK.from_dict(public, algorithm='RS256').key
        if key.key_size < 2048:
            raise ValueError('Weak identity key')
        try:
            matches.append(jwt.decode(compact, key, algorithms=['RS256'], **options))
        except jwt.PyJWTError:
            pass
    if len(matches) != 1:
        raise ValueError('Identity signature rejected')
    return matches[0]


def exchange(mapping, protected_claims, subject, *, allow_loopback=False):
    token = protected_claims[mapping['access_token_claim']]
    access = verify(token, mapping['access_token_jwks'], issuer=mapping['issuer'], audience=mapping['audience'],
                    options={'require': ['iss', 'aud', 'sub', 'iat', 'exp']})
    if access['sub'] != subject:
        raise ValueError('Identity session subject mismatch')
    url = urlsplit(mapping['userinfo_url'])
    loopback = allow_loopback and url.hostname in ['127.0.0.1', '::1'] and url.scheme == 'http'
    if not (url.scheme == 'https' or loopback) or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Fixed secure identity endpoint required')
    context = ssl.create_default_context(cafile=mapping.get('ca_file'))
    with httpx.Client(trust_env=False, verify=context, timeout=5, follow_redirects=False) as client:
        with client.stream('GET', url.geturl(), headers={'Authorization': 'Bearer ' + token}) as response:
            if response.status_code != 200:
                raise ValueError('Identity exchange failed')
            raw = bytearray()
            deadline = time.monotonic() + 5
            for chunk in response.iter_bytes(chunk_size=65536):
                raw.extend(chunk)
                if len(raw) > 512 * 1024 or time.monotonic() > deadline:
                    raise ValueError('Identity response too large or slow')
    assertion = raw.decode('utf-8')
    if mapping.get('encrypted_response') is True:
        try:
            if assertion.count('.') != 4:
                raise ValueError('Compact encrypted identity required')
            message = jwe.JWE(algs=['RSA-OAEP-256', 'A256GCM'])
            message.deserialize(assertion)
            if message.jose_header.get('alg') != 'RSA-OAEP-256' or message.jose_header.get('enc') != 'A256GCM' or any(
                    k in message.jose_header for k in ['zip', 'crit', 'jku', 'x5u', 'jwk']):
                raise ValueError('Unsupported identity encryption')
            message.decrypt(jwk.JWK.from_pem(Path(mapping['recipient_key_file']).read_bytes()))
            assertion = message.payload.decode('utf-8')
        except JWException:
            raise ValueError('Identity decryption rejected') from None
    elif assertion.count('.') != 2:
        raise ValueError('Signed identity assertion required')
    claims = verify(assertion, mapping['identity_jwks'], options={'verify_aud': False, 'require': ['sub']})
    if claims['sub'] != access['sub']:
        raise ValueError('Exchanged identity subject mismatch')
    columns = mapping['columns']
    if not isinstance(columns, list) or not columns or len(columns) > 128 or any(not isinstance(k, str) or not k for k in columns):
        raise ValueError('Explicit identity claims required')
    return {name: claims[name] for name in columns}
