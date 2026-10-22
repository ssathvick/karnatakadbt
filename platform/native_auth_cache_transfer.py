"""Fenced Redis state mirroring with absolute expiry and deletion propagation."""
import time


SNAPSHOT = """
local payload=redis.call('DUMP',KEYS[1]);if not payload then return {} end
local ttl=redis.call('PTTL',KEYS[1]);local now=redis.call('TIME')
local millis=tonumber(now[1])*1000+math.floor(tonumber(now[2])/1000)
if ttl == -2 then return {} end
return {payload,ttl == -1 and 0 or millis+ttl}
"""


class CacheTransferBlocked(ValueError):
    pass


def snapshot(client, *, excluded, maximum_keys=100000, maximum_bytes=64 * 1024 * 1024):
    records, size = {}, 0
    for key in client.scan_iter(count=200):
        if key in excluded:
            continue
        value = client.eval(SNAPSHOT, 1, key)
        if not value:
            continue
        size += len(key) + len(value[0])
        if len(records) >= maximum_keys or size > maximum_bytes or len(value[0]) > 1024 * 1024:
            raise CacheTransferBlocked('Cache transfer exceeds bounded capacity')
        records[key] = (value[0], int(value[1]))
    return records


def mirror(source, destination, *, fenced, excluded=frozenset({b'kdbt-native-authorization-owner'})):
    def require_fence():
        if fenced() is not True:
            raise CacheTransferBlocked('Both authorities must remain fenced')
    require_fence()
    source_now, destination_now = source.time(), destination.time()
    if abs((source_now[0] - destination_now[0]) * 1000000 + source_now[1] - destination_now[1]) > 1000000:
        raise CacheTransferBlocked('Cache clocks differ by more than one second')
    retained = snapshot(source, excluded=excluded)
    old = snapshot(destination, excluded=excluded)
    copied, expired, removed = 0, 0, 0
    for key, (payload, deadline) in retained.items():
        require_fence()
        current = source.eval(SNAPSHOT, 1, key)
        if not current:
            destination.delete(key)
            expired += 1
            continue
        if bytes(current[0]) != payload or abs(int(current[1]) - deadline) > 2:
            raise CacheTransferBlocked('Source changed during fenced transfer')
        clock = destination.time()
        if deadline and deadline <= clock[0] * 1000 + clock[1] // 1000:
            destination.delete(key)
            expired += 1
            continue
        destination.restore(key, deadline, payload, replace=True, absttl=bool(deadline))
        copied += 1
    for key in set(old) - set(retained):
        require_fence()
        destination.delete(key)
        removed += 1
    require_fence()
    before = snapshot(source, excluded=excluded)
    after = snapshot(destination, excluded=excluded)
    now = source.time();clock = now[0] * 1000 + now[1] // 1000
    before = {k: v for k, v in before.items() if not v[1] or v[1] > clock + 10}
    after = {k: v for k, v in after.items() if not v[1] or v[1] > clock + 10}
    if set(before) != set(after) or any(before[k][0] != after[k][0] or abs(before[k][1] - after[k][1]) > 2 for k in before):
        raise CacheTransferBlocked('Cache contents or absolute expiry differ after transfer')
    require_fence()
    return {'copied': copied, 'expired_during_transfer': expired, 'removed_from_destination': removed,
            'contents_and_absolute_expiry_verified': True}
