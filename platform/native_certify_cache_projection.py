"""Build a bounded legacy-cache projection from decrypted native SQL state.

This module performs no deployment or cache mutation. Callers must take a
coordinated fenced SQL snapshot and install the complete result, rather than
merge it with caches that can contain already-consumed authorizations.
Nonzero counters additionally require the retained SQL guard. Its presence
does not prove routing: callers must fence and route every token request
through that guard before installing the projection.
"""
import hashlib
import io
import math
import re
import struct


class ProjectionBlocked(ValueError):
    pass


BUSINESS_CACHES = ('credentialOfferCache', 'preAuthCodeCache', 'vcissuance')


def project(wire, authorizations, sessions, *, issuer, now, failed_code_guard=None):
    if not isinstance(issuer, str) or not issuer.startswith('https://') or not math.isfinite(now):
        raise ProjectionBlocked('Explicit HTTPS issuer and snapshot time required')
    result = {name: {} for name in BUSINESS_CACHES}
    seen = set()
    total_bytes, total_rows = 0, 0

    def add(cache, key, value, expires):
        nonlocal total_bytes
        if not isinstance(key, str) or not key or len(key) > 4096 or key in result[cache]:
            raise ProjectionBlocked('Duplicate or invalid recovery cache key')
        if not isinstance(value, bytes) or not 0 < len(value) <= 1024 * 1024:
            raise ProjectionBlocked('Invalid bounded recovery cache value')
        total_bytes += len(key.encode()) + len(value)
        if total_bytes > 32 * 1024 * 1024:
            raise ProjectionBlocked('Recovery state byte bound exceeded')
        result[cache][key] = (value, expires)
        if sum(len(items) for items in result.values()) > 100000:
            raise ProjectionBlocked('Recovery entry bound exceeded')

    for row in authorizations:
        total_rows += 1
        if total_rows > 100000:
            raise ProjectionBlocked('Recovery source row bound exceeded')
        identifier, payload, expires = row['id'], row['payload'], row['expires_at']
        if identifier in seen:
            raise ProjectionBlocked('Duplicate authorization row')
        seen.add(identifier)
        if not math.isfinite(expires):
            raise ProjectionBlocked('Invalid authorization expiry')
        if expires <= now or row['used_at'] is not None:
            continue
        if row['kind'] != 'PREAUTH':
            raise ProjectionBlocked('IAR requires the coordinated SQL projection adapter')
        if type(row['attempts']) is not int or not 0 <= row['attempts'] <= 5:
            raise ProjectionBlocked('Invalid failed-code counter')
        # The original cache does not preserve the native failed-code counter.
        # Refusing avoids granting fresh guesses after a rollback.
        if row['attempts'] != 0:
            from native_certify_failed_code_recovery import FailedCodeRecovery, RecoveryGrantRejected
            if not isinstance(failed_code_guard, FailedCodeRecovery):
                raise ProjectionBlocked('Original engine cannot preserve failed-code attempts without a recovery guard')
            try:
                failed_code_guard.verify_projection(row)
            except RecoveryGrantRejected:
                raise ProjectionBlocked('Failed-code guard state differs from projection') from None
            if row['attempts'] >= 5:
                continue
        code, offer = payload.get('code'), payload.get('offer')
        if not isinstance(code, str) or not isinstance(offer, str):
            raise ProjectionBlocked('Pending authorization recovery secrets unavailable')
        if hashlib.sha256(code.encode()).hexdigest() != identifier or hashlib.sha256(offer.encode()).hexdigest() != row['offer_hash']:
            raise ProjectionBlocked('Authorization recovery identity mismatch')
        add('credentialOfferCache', 'credential_offer:' + offer, wire.offer(payload, issuer), expires)
        add('preAuthCodeCache', 'pre_auth_code:' + code, wire.code(payload, expires), expires)

    seen.clear()
    for row in sessions:
        total_rows += 1
        if total_rows > 100000:
            raise ProjectionBlocked('Recovery source row bound exceeded')
        identifier, payload, expires = row['id'], row['payload'], row['expires_at']
        if identifier in seen:
            raise ProjectionBlocked('Duplicate credential session row')
        seen.add(identifier)
        if not math.isfinite(expires):
            raise ProjectionBlocked('Invalid session expiry')
        if expires <= now:
            continue
        revoked_at=row.get('revoked_at') if row.get('revoked_at') is not None else payload.get('revoked_at')
        if revoked_at is not None:
            # Projection replaces the complete authoritative vcissuance map.
            # Omission removes the token's cached nonce/claims; the retained
            # issuance handler cannot authorize it. Keep the native revocation
            # journal intact so a later forward import cannot revive it.
            if type(revoked_at) not in (int,float) or not math.isfinite(revoked_at):
                raise ProjectionBlocked('Invalid session revocation time')
            continue
        token_hash = payload.get('access_token_hash')
        if not isinstance(token_hash, str) or not token_hash or len(token_hash) > 128:
            raise ProjectionBlocked('Session token recovery hash unavailable')
        add('vcissuance', token_hash, wire.transaction(payload, expires), expires)
    return result


def encode_snapshot(caches, *, snapshot_time, install_time, maximum_bytes=32 * 1024 * 1024):
    """Encode the snapshot-agent frame, omitting entries expired during handoff.

    Dates inside serialized DTOs retain their original absolute values. This
    framing has no TTL-renewal operation. Installers must fence both producers
    and workers; this encoder is deliberately insufficient to authorize one.
    """
    from native_certify_recovery_wire import java, javaobj
    if not all(math.isfinite(t) for t in (snapshot_time, install_time)) or install_time < snapshot_time:
        raise ProjectionBlocked('Monotonic handoff times required')
    if set(caches) != set(BUSINESS_CACHES):
        raise ProjectionBlocked('Complete authoritative business-cache set required')
    stream = io.BytesIO()

    def text(value):
        encoded = value.encode('ascii')
        stream.write(struct.pack('>H', len(encoded)) + encoded)

    text('KDBT-CERTIFY-CACHE-V2')
    stream.write(struct.pack('>i', len(caches)))
    for name in BUSINESS_CACHES:
        active = [(key, value, expires) for key, (value, expires) in sorted(caches[name].items()) if expires > install_time]
        text(name)
        stream.write(struct.pack('>i', len(active)))
        for key, value, expires in active:
            encoded_key = javaobj.dumps(java(key))
            for encoded in (encoded_key, value):
                stream.write(struct.pack('>i', len(encoded)) + encoded)
            stream.write(struct.pack('>q',int(expires*1000)))
            if stream.tell() > maximum_bytes:
                raise ProjectionBlocked('Recovery frame bound exceeded')
    return stream.getvalue()


def import_transaction(wire, serialized, token_hash, *, configuration, now, observed_expires_at):
    """Translate a retained VC transaction without possessing its bearer token.

    This returns data only. Explicit runtime enablement and strict verification
    of the subsequently presented original JWT remain mandatory in the native
    authorization service. The token's verified expiry further caps this row.
    """
    from native_certify_recovery_wire import javaobj
    from native_auth_cache import plain
    if not isinstance(serialized, bytes) or not 4 <= len(serialized) <= 1024 * 1024:
        raise ProjectionBlocked('Bounded serialized transaction required')
    if not isinstance(token_hash, str) or not re.fullmatch(r'[A-Za-z0-9_-]{22}', token_hash):
        raise ProjectionBlocked('Original truncated SHA-256 token hash required')
    if not all(math.isfinite(t) for t in (now, observed_expires_at)):
        raise ProjectionBlocked('Explicit observed expiry required')
    try:
        obj = javaobj.loads(serialized)
        expected = wire.templates['transaction'].classdesc
        if obj.classdesc.name != expected.name or obj.classdesc.serialVersionUID != expected.serialVersionUID:
            raise ProjectionBlocked('Unknown original transaction descriptor')
        value = plain(obj)
        issued, lifetime = value['cNonceIssuedEpoch'], value['cNonceExpireSeconds']
        if type(issued) is not int or type(lifetime) is not int or not 0 < lifetime <= 86400 or issued <= 0 or issued > now + 30:
            raise ProjectionBlocked('Invalid original nonce lifetime')
        expires = min(observed_expires_at, issued + lifetime)
        if expires <= now:
            raise ProjectionBlocked('Expired original transaction')
        if not isinstance(value['cNonce'], str) or not 1 <= len(value['cNonce']) <= 4096 or not isinstance(value['claims'], dict):
            raise ProjectionBlocked('Invalid original nonce or claims')
        if configuration['credential_config_key_id'] != value['credentialConfigurationId'] or str(configuration['status']).lower() != 'active':
            raise ProjectionBlocked('Original credential configuration unavailable')
        created = value['createdAt']
        if type(created) is not int or created <= 0:
            raise ProjectionBlocked('Invalid original transaction creation time')
        if created > 10 ** 12:
            created //= 1000
        if created > now + 30:
            raise ProjectionBlocked('Future original transaction creation time')
        identifier = hashlib.sha256(('source-access:' + token_hash).encode()).hexdigest()
        payload = {'configuration': value['credentialConfigurationId'], 'scope': configuration['scope'],
                   'claims': value['claims'], 'created_at': created, 'nonce': value['cNonce'],
                   'nonce_issued_at': issued, 'client_id': None, 'access_token_hash': token_hash,
                   'imported_original_cache': True, 'source_cache_sha256': hashlib.sha256(serialized).hexdigest()}
        return identifier, payload, expires
    except (KeyError, TypeError, AttributeError, ValueError, IndexError) as error:
        if isinstance(error, ProjectionBlocked):
            raise
        raise ProjectionBlocked('Invalid original credential transaction') from None
