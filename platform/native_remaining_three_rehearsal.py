"""Private, expiring admission for a fenced NATIVE rollback rehearsal.

This is deliberately separate from public production acceptance. Losing the
maintenance fence closes this admission; it never promotes a receipt to LIVE.
Normal endpoint authentication remains mandatory after this transport gate.
"""
import hashlib
import hmac
import ipaddress
import json
import os
import stat
import time
from pathlib import Path

ROOT = Path('/opt/karnatakadbt/private/mosip-migration/remaining-three/production-cutover')
HEADER = 'x-kdbt-private-rehearsal'


def settings_hash(settings):
    selected = {k: v for k, v in settings.items() if k != 'rehearsal_receipt'}
    return hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def release_hashes(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(directory).glob('*.py'))}


def private_read(path):
    # Pin the descriptor, reject links and require an operator-owned private file.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > 1024 * 1024:
            raise ValueError('Private root-owned bounded admission file required')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            body = stream.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            raise ValueError('Admission file too large')
        return info, body
    finally:
        os.close(fd)


class FencedRehearsal:
    def __init__(self, settings, directory, component):
        if settings.get('environment') != 'NATIVE' or component not in {'authorization', 'certify'}:
            raise ValueError('Explicit native rehearsal component required')
        self.settings = settings_hash(settings)
        self.release = release_hashes(directory)
        self.component = component
        self.path = Path(settings['rehearsal_receipt'])
        # Reject path traversal through linked parent directories as well.
        if self.path.parent != ROOT or self.path.resolve(strict=True) != self.path:
            raise ValueError('Protected rehearsal receipt location required')
        info, self.body = private_read(self.path)
        self.inode = (info.st_dev, info.st_ino)
        self.receipt = json.loads(self.body)
        self.require()

    def require(self):
        info, body = private_read(self.path)
        r = self.receipt
        now = time.time()
        if ((info.st_dev, info.st_ino) != self.inode or not hmac.compare_digest(body, self.body)
                or r.get('kind') != 'FENCED_REHEARSAL' or r.get('component') != self.component
                or r.get('settings_sha256') != self.settings or r.get('release_sha256') != self.release
                or type(r.get('issued_at')) not in (int, float) or type(r.get('expires_at')) not in (int, float)
                or not r['issued_at'] <= now < r['expires_at'] <= r['issued_at'] + 900
                or not isinstance(r.get('operation'), str) or not r['operation']
                or not isinstance(r.get('capability_sha256'), str) or len(r['capability_sha256']) != 64):
            raise ValueError('Invalid or expired private rehearsal admission')
        fence, content = private_read(ROOT / 'producer-fence.json')
        if (r.get('fence_device') != fence.st_dev or r.get('fence_inode') != fence.st_ino
                or r.get('fence_sha256') != hashlib.sha256(content).hexdigest()
                or json.loads(content).get('operation') != r['operation']):
            raise ValueError('Exact owning maintenance fence required')
        return True

    def allows(self, request):
        try:
            self.require()
            # No forwarded headers are trusted. A public reverse proxy may be
            # loopback too, so it still needs the unlogged private capability.
            if not request.client or not ipaddress.ip_address(request.client.host).is_loopback:
                return False
            values = request.headers.getlist(HEADER)
            if len(values) != 1 or not 32 <= len(values[0]) <= 256:
                return False
            return hmac.compare_digest(hashlib.sha256(values[0].encode()).hexdigest(), self.receipt['capability_sha256'])
        except (OSError, ValueError, TypeError, KeyError):
            return False


def admission(settings, directory, component):
    if 'rehearsal_receipt' not in settings:
        return None
    return FencedRehearsal(settings, directory, component)
