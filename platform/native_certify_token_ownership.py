"""Read the pinned credential writer barrier; never infer ownership from HTTP."""
import sqlite3
import stat
from pathlib import Path

BASE = Path('/opt/karnatakadbt/private/mosip-migration/remaining-three')


class CertifyTokenOwnership:
    def __init__(self, database):
        self.path = Path(database)
        if self.path != BASE / 'native-certify/authority.sqlite' or self.path.resolve(strict=True) != self.path:
            raise ValueError('Exact native credential authority required')
        info = self.path.stat()
        self.identity = info.st_dev, info.st_ino
        self.read()

    def read(self):
        info = self.path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077
                or (info.st_dev, info.st_ino) != self.identity):
            raise ValueError('Credential authority identity or permissions changed')
        with sqlite3.connect('file:' + str(self.path) + '?mode=ro', uri=True, timeout=3) as connection:
            rows = connection.execute('SELECT id,owner FROM km_authority').fetchall()
        if rows == [(1, 'NATIVE')]:
            return 'NATIVE'
        if rows == [(1, 'CANDIDATE')]:
            return 'LEGACY'
        if rows == [(1, 'FENCED')]:
            return 'FENCED'
        raise ValueError('Credential writer topology is unknown')
