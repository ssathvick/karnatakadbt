"""Project native userinfo encryption into the retained DTO representation.

The original userinfo business API returns encryptedKyc directly. Its retained
representation is the provider-signed JWT, whereas the native engine encrypts
that JWT at rest. Only this field changes; native ciphertext remains intact in
the authoritative native cache. Both services must be fenced throughout.
"""
import jwt
from native_auth_cache_transfer import snapshot, mirror, CacheTransferBlocked

EXCLUDED = frozenset({b'kdbt-native-authorization-owner'})
CAS = """if redis.call('GET',KEYS[1])~=ARGV[1] then return 0 end
redis.call('SET',KEYS[1],ARGV[2],'XX','KEEPTTL');return 1"""


def project_userinfo(source, destination, *, codec, cipher, verification_keys, fenced):
    if not callable(fenced) or fenced() is not True or not verification_keys:
        raise CacheTransferBlocked('Closed producers and pinned identity verification keys required')
    snapshots = snapshot(source, excluded=EXCLUDED)
    plans = []
    # Validate the complete source set before the first destination mutation.
    for key in sorted(snapshots):
        if not key.startswith(b'userinfo::'):
            continue
        if fenced() is not True:
            raise CacheTransferBlocked('Producer fence changed before userinfo projection')
        before = source.get(key)
        if before is None:
            continue
        state = codec.decode(before)
        expected_hash = key[len(b'userinfo::'):].decode('ascii')
        if (state.get('aHash') != expected_hash or not isinstance(state.get('clientId'), str)
                or not state['clientId'] or not isinstance(state.get('partnerSpecificUserToken'), str)):
            raise CacheTransferBlocked('Userinfo transaction/hash/client binding differs')
        value = state.get('encryptedKyc')
        if not isinstance(value, str) or not value:
            raise CacheTransferBlocked('Signed identity payload missing')
        signed = cipher.decrypt(value) if value.startswith(cipher.PREFIX) else value
        try:
            header = jwt.get_unverified_header(signed)
            if header.get('alg') != 'RS256' or header.get('crit'):
                raise ValueError()
            matches = []
            for public in verification_keys:
                try:
                    matches.append(jwt.decode(signed, public, algorithms=['RS256'],
                        options={'verify_aud': False, 'require': ['sub']}))
                except jwt.PyJWTError:
                    pass
            if len(matches) != 1 or matches[0]['sub'] != state['partnerSpecificUserToken']:
                raise ValueError()
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            raise CacheTransferBlocked('Pinned identity signature/subject validation failed') from None
        state['encryptedKyc'] = signed
        projected = codec.encode(state, rebuild_fields=('encryptedKyc',))
        plans.append((key, before, projected))
    copied = mirror(source, destination, fenced=fenced, excluded=EXCLUDED)
    changed = 0
    for key, before, projected in plans:
        if fenced() is not True:
            raise CacheTransferBlocked('Producer fence changed before legacy userinfo installation')
        # Do not revive an entry that expired during mirroring.
        if not destination.exists(key):
            continue
        if source.get(key) != before:
            raise CacheTransferBlocked('Native userinfo changed during projection')
        expiry = destination.pexpiretime(key)
        if expiry <= 0 or source.pexpiretime(key) != expiry:
            raise CacheTransferBlocked('Absolute userinfo expiry differs before projection')
        if destination.eval(CAS, 1, key, before, projected) != 1:
            raise CacheTransferBlocked('Retained userinfo changed before installation')
        if destination.get(key) != projected or destination.pexpiretime(key) != expiry or source.get(key) != before:
            raise CacheTransferBlocked('Userinfo projection, expiry or native ciphertext differs')
        changed += before != projected
    if fenced() is not True:
        raise CacheTransferBlocked('Producer fence changed after userinfo projection')
    return {'cache': copied, 'userinfo_rows_validated': len(plans), 'userinfo_rows_transformed': changed,
            'native_ciphertext_preserved': True, 'subject_signature_and_absolute_expiry_verified': True}
