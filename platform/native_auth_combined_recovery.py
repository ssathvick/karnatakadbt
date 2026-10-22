"""Journaled signing-vault and encrypted-session recovery under closed fences.

Business SQL and ownership/routing require their own coordinated adapters. This
operation never opens a writer barrier, starts workers, or authorizes cutover.
"""
import base64
import fcntl
import hmac
import json
import os
import secrets
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from native_auth_cache_transfer import snapshot, mirror
from native_auth_signing import NativeSigningAuthority
from native_auth_state_transfer import merge_signing_vault

BASE = Path('/opt/karnatakadbt/private/mosip-migration/remaining-three')
EXCLUDED = frozenset({b'kdbt-native-authorization-owner'})


def restore_bundle(directory, side, destination_settings, destination_cache, *, fenced):
    """Physically recover one authenticated checkpoint into fresh fenced stores.

    Never overwrite an existing vault or a populated cache. Redis expiration
    timestamps remain absolute; expired entries are omitted during recovery.
    """
    if not callable(fenced) or fenced() is not True or side not in {'source', 'destination'}:
        raise ValueError('Explicit side and observed closed writer/worker fence required')
    directory = Path(directory).resolve(strict=True)
    if not directory.is_relative_to(BASE) or directory.stat().st_uid != 0 or directory.stat().st_mode & 0o077:
        raise ValueError('Private combined recovery checkpoint required')
    for name, bound in [('backup.key', 32), ('backup.bin', 256 * 1024 * 1024 + 28)]:
        path = directory / name
        if path.stat().st_uid != 0 or path.stat().st_mode & 0o077 or path.stat().st_size > bound:
            raise ValueError('Private bounded recovery material required')
    raw = (directory / 'backup.bin').read_bytes()
    try:
        bundle = json.loads(AESGCM((directory / 'backup.key').read_bytes()).decrypt(raw[:12], raw[12:], b'kdbt-auth-combined-recovery-v1'))
    except Exception:
        raise ValueError('Combined checkpoint authentication failed') from None
    selection = bundle['states'][side]
    if (selection['signing_scope'] != destination_settings['signing']['scope']
            or not hmac.compare_digest(bundle['cache_key'], destination_settings['cache_key'])):
        raise ValueError('Signing scope or cache encryption key differs from checkpoint')
    vault_path = Path(destination_settings['signing']['directory']).resolve()
    if not vault_path.is_relative_to(BASE) or vault_path.exists() or destination_cache.dbsize() != 0:
        raise ValueError('Fresh vault and empty dedicated cache required')
    if set(selection['vault_files']) != {'master.key', 'vault.bin'} or len(selection['cache']) > 100000:
        raise ValueError('Bounded complete checkpoint required')
    records, size = {}, 0
    for key, value, deadline in selection['cache']:
        key, value = base64.b64decode(key, validate=True), base64.b64decode(value, validate=True)
        size += len(key) + len(value)
        if (key in records or key in EXCLUDED or type(deadline) is not int or deadline < 0
                or len(value) > 1024 * 1024 or size > 64 * 1024 * 1024):
            raise ValueError('Invalid bounded checkpoint cache record')
        records[key] = (value, deadline)
    files = {name: base64.b64decode(value, validate=True) for name, value in selection['vault_files'].items()}
    if len(files['master.key']) != 32 or len(files['vault.bin']) > 16 * 1024 * 1024:
        raise ValueError('Bounded encrypted signing files required')
    if fenced() is not True:
        raise ValueError('Recovery fence changed before material installation')
    vault_path.mkdir(mode=0o700)
    for name, value in files.items():
        with (vault_path / name).open('xb') as stream:
            os.chmod(stream.name, 0o600)
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    authority = NativeSigningAuthority(destination_settings['signing'])
    entries = len(authority.read())
    restored, expired = 0, 0
    for key, (value, deadline) in records.items():
        if fenced() is not True:
            raise ValueError('Recovery fence changed; restored stores remain closed')
        now = destination_cache.time()
        if deadline and deadline <= now[0] * 1000 + now[1] // 1000:
            expired += 1
            continue
        destination_cache.restore(key, deadline, value, replace=False, absttl=bool(deadline))
        restored += 1
    observed = snapshot(destination_cache, excluded=EXCLUDED)
    now = destination_cache.time()
    clock = now[0] * 1000 + now[1] // 1000
    expected = {key: pair for key, pair in records.items() if not pair[1] or pair[1] > clock + 10}
    observed = {key: pair for key, pair in observed.items() if not pair[1] or pair[1] > clock + 10}
    if set(expected) != set(observed) or any(expected[k][0] != observed[k][0] or abs(expected[k][1] - observed[k][1]) > 2 for k in expected):
        raise ValueError('Recovered cache differs from authenticated checkpoint')
    if fenced() is not True:
        raise ValueError('Recovery fence changed before verification completed')
    return {'authenticated_checkpoint_physically_restored': True, 'restored_cache_entries': restored,
            'expired_entries_omitted': expired, 'signing_entries': entries, 'writers_released': False}


def transfer(source_settings, destination_settings, source_cache, destination_cache, *, directory, fenced):
    def require_fence():
        if not callable(fenced) or fenced() is not True:
            raise ValueError('Observed writer and worker fence required throughout combined recovery')

    require_fence()
    directory = Path(directory).resolve()
    if not directory.is_relative_to(BASE) or directory.exists():
        raise ValueError('Fresh private combined recovery journal required')
    source_key = base64.b64decode(source_settings['cache_key'], validate=True)
    target_key = base64.b64decode(destination_settings['cache_key'], validate=True)
    if len(source_key) != 32 or not hmac.compare_digest(source_key, target_key):
        raise ValueError('Cache encryption keys differ; explicit reencryption is required')
    source_identity = (source_cache.info('server')['run_id'], source_cache.connection_pool.connection_kwargs.get('db', 0))
    destination_identity = (destination_cache.info('server')['run_id'], destination_cache.connection_pool.connection_kwargs.get('db', 0))
    if source_identity == destination_identity:
        raise ValueError('Distinct cache authorities required')
    source_vault, target_vault = (NativeSigningAuthority(s['signing']) for s in (source_settings, destination_settings))
    if source_vault.path.resolve() == target_vault.path.resolve():
        raise ValueError('Distinct signing vaults required')
    directory.mkdir(mode=0o700)
    lock = (directory / 'operation.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def record(phase, **extra):
        temporary = directory / 'journal.next'
        temporary.write_text(json.dumps({'phase': phase, 'writers_released': False, **extra}))
        temporary.chmod(0o600)
        with temporary.open('rb') as stream:
            os.fsync(stream.fileno())
        temporary.replace(directory / 'journal.json')
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    try:
        record('CAPTURING')
        retained = {}
        for name, cache, vault in [('source', source_cache, source_vault), ('destination', destination_cache, target_vault)]:
            require_fence()
            values = snapshot(cache, excluded=EXCLUDED)
            files = {}
            for filename in ('master.key', 'vault.bin'):
                path = vault.path / filename
                if path.stat().st_size > 16 * 1024 * 1024:
                    raise ValueError('Signing backup size bound exceeded')
                files[filename] = base64.b64encode(path.read_bytes()).decode()
            retained[name] = {'cache': [[base64.b64encode(k).decode(), base64.b64encode(v).decode(), expiry]
                                      for k, (v, expiry) in sorted(values.items())], 'vault_files': files,
                              'signing_scope': vault.settings['scope']}
        payload = json.dumps({'cache_key': source_settings['cache_key'], 'states': retained}, separators=(',', ':')).encode()
        if len(payload) > 256 * 1024 * 1024:
            raise ValueError('Combined encrypted backup bound exceeded')
        key, nonce = secrets.token_bytes(32), secrets.token_bytes(12)
        for name, data in [('backup.key', key), ('backup.bin', nonce + AESGCM(key).encrypt(nonce, payload, b'kdbt-auth-combined-recovery-v1'))]:
            with (directory / name).open('xb') as stream:
                os.chmod(stream.name, 0o600)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        require_fence()
        record('BACKUP_DURABLE')
        result = merge_signing_vault(source_settings['signing'], destination_settings['signing'])
        before = source_vault.read()
        merged = target_vault.read()
        if any(merged.get(alias) != value for alias, value in before.items()):
            raise ValueError('Source signing material is absent from destination')
        require_fence()
        record('SIGNING_MATERIAL_VERIFIED')
        caches = mirror(source_cache, destination_cache, fenced=fenced, excluded=EXCLUDED)
        require_fence()
        record('COMPLETE', encrypted_backup_retained=True, signing_entries=result['merged_entries'], cache=caches)
        return {'signing': result, 'cache': caches, 'encrypted_prewrite_backup_retained': True,
                'shared_cache_encryption_key_verified': True, 'writers_released': False}
    except Exception:
        record('BLOCKED')
        raise
    finally:
        lock.close()
