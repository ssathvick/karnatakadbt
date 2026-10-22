"""Scoped RS256/PS256 JWS compatibility, including RFC 7797 payloads.

Certificate URLs are metadata only. This module never fetches an arbitrary URL
from a JWT or trusts a certificate merely because it is embedded in a header.
"""
import base64, binascii, json, secrets, zlib
from cryptography import x509
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from native_keymanager import VaultFailure, certificate, stamp
from native_key_vault import encode, canonical


def unbase(value):
    if not isinstance(value, str) or len(value) > 2*1024*1024:
        raise VaultFailure('Bounded base64 data is required')
    try:
        return base64.b64decode(value+'='*(-len(value) % 4), altchars=b'-_', validate=True)
    except (ValueError, binascii.Error):
        raise VaultFailure('Invalid base64 data')


def flag(request, name, default=False):
    result = request.get(name, default)
    if not isinstance(result, bool):
        raise VaultFailure('Boolean flag required')
    return result


def algorithm(value):
    if value == 'RS256':
        return padding.PKCS1v15()
    if value == 'PS256':
        return padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)
    raise VaultFailure('Unsupported signature algorithm')


def sign(engine, request, *, jws=False):
    application, reference = request.get('applicationId'), request.get('referenceId') or ''
    engine.policy(application, reference)
    payload = unbase(request.get('dataToSign'))
    if flag(request, 'validateJson', False):
        json.loads(payload)
    payload.decode('utf-8')
    with engine.vault.connect() as c:
        row = engine._row(c, application, reference)
        cert = certificate(row['certificate']); engine._valid(cert)
        key = engine.vault._private(row)
    alg = request.get('signAlgorithm', 'RS256') if jws else 'RS256'
    header = {'alg': alg, 'kid': engine.jose_id(row)}
    if flag(request, 'includeCertificate'):
        header['x5c'] = [base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()]
    if flag(request, 'includeCertHash'):
        header['x5t#S256'] = encode(cert.fingerprint(hashes.SHA256()))
    url = request.get('certificateUrl')
    if url:
        if not isinstance(url, str) or len(url) > 2048 or not url.startswith('https://'):
            raise VaultFailure('An HTTPS certificate metadata URL is required')
        header['x5u'] = url
    encoded = flag(request, 'b64JWSHeaderParam', True) if jws else True
    if not encoded:
        header.update(b64=False, crit=['b64'])
    body = encode(payload) if encoded else payload.decode('utf-8')
    included = flag(request, 'includePayload')
    if included and not encoded and '.' in body:
        raise VaultFailure('Unencoded compact payload cannot contain a period')
    head = encode(canonical(header))
    signed = (head+'.'+body).encode('utf-8')
    signature = key.sign(signed, algorithm(alg), hashes.SHA256())
    return {'jwtSignedData': head+'.'+(body if included else '')+'.'+encode(signature), 'timestamp': stamp(engine.clock())}


def verify(engine, request):
    application, reference = request.get('applicationId'), request.get('referenceId') or ''
    engine.policy(application, reference)
    compact = request.get('jwtSignatureData')
    if not isinstance(compact, str) or len(compact) > 2*1024*1024:
        raise VaultFailure('Bounded compact JWS required')
    pieces = compact.split('.')
    if len(pieces) != 3:
        raise VaultFailure('Invalid compact JWS')
    head, body, signature = pieces
    header = json.loads(unbase(head))
    if not isinstance(header, dict) or set(header)-{'alg','kid','x5c','x5t#S256','x5u','typ','b64','crit'}:
        raise VaultFailure('Unsupported JWS header')
    alg = algorithm(header.get('alg'))
    encoded = header.get('b64', True)
    if not isinstance(encoded, bool) or (header.get('crit') not in (None, [], ['b64'])) or (not encoded and header.get('crit') != ['b64']):
        raise VaultFailure('Unsupported critical JWS header')
    if request.get('actualData') is not None:
        if body:
            raise VaultFailure('Detached data cannot replace an included payload')
        actual = request['actualData']
        if not isinstance(actual, str) or len(actual) > 1024*1024:
            raise VaultFailure('Bounded detached UTF-8 payload required')
        body = encode(actual.encode()) if encoded else actual
    with engine.vault.connect() as c:
        rows = c.execute('''SELECT k.*,t.certificate FROM vault_keys k JOIN km_certificates t ON k.id=t.key_id
WHERE k.application=? AND k.reference=? AND k.state IN ('ACTIVE','VERIFY_ONLY')''', (application, reference)).fetchall()
    cert = None
    supplied = request.get('certificateData')
    if supplied:
        cert = certificate(supplied)
    elif header.get('x5c'):
        chain = header['x5c']
        if not isinstance(chain, list) or not 1 <= len(chain) <= 10:
            raise VaultFailure('Invalid certificate header')
        cert = x509.load_der_x509_certificate(unbase(chain[0]))
    else:
        candidates = [r for r in rows if engine.jose_id(r) == header.get('kid') or r['id']==header.get('kid')]
        if not candidates and not header.get('kid'):
            candidates = [r for r in rows if r['state'] == 'ACTIVE']
        if len(candidates) != 1:
            raise VaultFailure('Signing certificate is not registered in this scope')
        cert = certificate(candidates[0]['certificate'])
    engine._valid(cert)
    if not isinstance(cert.public_key(), rsa.RSAPublicKey) or cert.public_key().key_size < 2048:
        raise VaultFailure('RSA certificate of at least 2048 bits required')
    # An embedded certificate cannot override revocation of a registered key.
    with engine.vault.connect() as c:
        revoked = c.execute('''SELECT t.certificate FROM vault_keys k JOIN km_certificates t ON k.id=t.key_id
WHERE k.state='REVOKED' AND k.application=? AND k.reference=?''', (application, reference)).fetchall()
    if any(certificate(r[0]).fingerprint(hashes.SHA256()) == cert.fingerprint(hashes.SHA256()) for r in revoked):
        raise VaultFailure('Signing certificate has been revoked')
    valid = False
    try:
        cert.public_key().verify(unbase(signature), (head+'.'+body).encode(), alg, hashes.SHA256())
        valid = True
    except InvalidSignature:
        pass
    trusted = 'Trust Not Verified'
    if flag(request, 'validateTrust'):
        trusted = 'Trust Valid' if engine.trust({'partnerDomain': request.get('domain'),
            'certificateData': cert.public_bytes(serialization.Encoding.PEM).decode()})['status'] else 'Trust Not Valid'
    return {'signatureValid': valid, 'message': 'Validation Successful' if valid else 'Validation Failed', 'trustValid': trusted}


def encrypt(engine, request):
    application, reference = request.get('applicationId'), request.get('referenceId') or ''
    engine.policy(application, reference)
    if request.get('x509Certificate'):
        cert = certificate(request['x509Certificate'])
    else:
        cert = certificate(engine.get(application, reference)['certificate'])
    engine._valid(cert)
    key = cert.public_key()
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 2048:
        raise VaultFailure('An RSA encryption certificate is required')
    plain = unbase(request.get('data'))
    if len(plain) > 1024*1024:
        raise VaultFailure('Payload exceeds one MiB')
    plain.decode('utf-8')
    json.loads(plain)
    fingerprint = encode(cert.fingerprint(hashes.SHA256()))
    header = {'alg':'RSA-OAEP-256','enc':'A256GCM','cty':'JWT','typ':'JWT','kid':fingerprint}
    if flag(request, 'enableDefCompression', True):
        compressor = zlib.compressobj(wbits=-15)
        plain = compressor.compress(plain)+compressor.flush()
        header['zip'] = 'DEF'
    if flag(request, 'includeCertificate'):
        header['x5c'] = [base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()]
    if flag(request, 'includeCertHash'):
        header['x5t#S256'] = fingerprint
    if request.get('jwkSetUrl'):
        url = request['jwkSetUrl']
        if not isinstance(url, str) or len(url) > 2048 or not url.startswith('https://'):
            raise VaultFailure('An HTTPS JWKS metadata URL is required')
        header['jku'] = url
    protected = encode(canonical(header)); cek = secrets.token_bytes(32); iv = secrets.token_bytes(12)
    wrapped = key.encrypt(cek, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    cipher = AESGCM(cek).encrypt(iv, plain, protected.encode())
    compact = '.'.join([protected,encode(wrapped),encode(iv),encode(cipher[:-16]),encode(cipher[-16:])])
    return {'data':compact,'timestamp':stamp(engine.clock())}


def decrypt(engine, request):
    application, reference = request.get('applicationId'), request.get('referenceId') or ''
    engine.policy(application, reference)
    compact = request.get('encData')
    try:
        if not isinstance(compact, str) or len(compact) > 2*1024*1024:
            raise ValueError()
        head, wrapped, nonce, body, tag = compact.split('.')
        header = json.loads(unbase(head))
        if not isinstance(header, dict) or set(header)-{'alg','enc','kid','zip','cty','typ','x5c','x5t#S256','jku'}:
            raise ValueError()
        if header.get('alg') != 'RSA-OAEP-256' or header.get('enc') != 'A256GCM' or header.get('zip') not in (None,'DEF'):
            raise ValueError()
        with engine.vault.connect() as c:
            rows = c.execute('''SELECT k.*,t.certificate FROM vault_keys k JOIN km_certificates t ON k.id=t.key_id
WHERE k.application=? AND k.reference=? AND k.state IN ('ACTIVE','VERIFY_ONLY') AND k.private_blob IS NOT NULL''',(application, reference)).fetchall()
        candidates = [dict(r) for r in rows if encode(certificate(r['certificate']).fingerprint(hashes.SHA256())) == header.get('kid')]
        if len(candidates) != 1:
            raise ValueError()
        row = candidates[0]
        # Retired private keys remain available for old ciphertext; revocation
        # removes that permission. No current alias is substituted for a kid.
        row['state'] = 'ACTIVE'; key = engine.vault._private(row)
        cek = key.decrypt(unbase(wrapped),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
        iv, cipher, authentication = unbase(nonce), unbase(body), unbase(tag)
        if len(iv) != 12 or len(authentication) != 16 or len(cek) != 32:
            raise ValueError()
        plain = AESGCM(cek).decrypt(iv,cipher+authentication,head.encode())
        if header.get('zip') == 'DEF':
            inflater = zlib.decompressobj(wbits=-15)
            plain = inflater.decompress(plain,1024*1024+1)
            if len(plain) > 1024*1024 or inflater.unconsumed_tail or inflater.unused_data or not inflater.eof:
                raise ValueError()
        if len(plain) > 1024*1024:
            raise ValueError()
        plain.decode('utf-8')
        return {'data':encode(plain),'timestamp':stamp(engine.clock())}
    except (ValueError, TypeError, KeyError, InvalidTag, zlib.error, VaultFailure):
        raise VaultFailure('Ciphertext authentication failed for this scope')
