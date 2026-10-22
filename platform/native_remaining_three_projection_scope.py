"""Narrow production database scope, separate from writer-release admission.

The root coordinator supplies an observed, closed runtime fence. This scope
permits data projection while that fence remains closed; it cannot release a
producer, admit NATIVE settings, change routing or stop a retained workload.
"""
import hashlib
import json
import os
from pathlib import Path


def fingerprint(configuration):
    return hashlib.sha256(json.dumps(configuration, sort_keys=True, separators=(',', ':')).encode()).digest()


class ProductionProjectionScope:
    def __init__(self, pairs, observer):
        if not callable(observer) or set(pairs) != {'esignet', 'certify'}:
            raise ValueError('Exact retained production projection domains required')
        self.pairs = {}
        self.observer = observer
        self.closed = False
        for schema, (retained, native) in pairs.items():
            expected = 'mosip_esignet' if schema == 'esignet' else 'inji_certify'
            if retained['dbname'] != expected or not native['dbname'].startswith('kdbt_native_') or retained['host'] != native['host']:
                raise ValueError('Pinned retained/native database pair required')
            self.pairs[schema] = frozenset((fingerprint(retained), fingerprint(native)))
        self.require()

    def require(self):
        if (self.closed or os.environ.get('WSL_DISTRO_NAME') != 'KarnatakaDBT'
                or Path('/proc/self/ns/net').stat().st_ino != Path('/run/netns/karnatakadbt').stat().st_ino
                or self.observer() is not True):
            raise ValueError('Observed production writer/worker fence required throughout projection')
        return True

    def authorize(self, source, destination, schema):
        self.require()
        if schema not in self.pairs or frozenset((fingerprint(source), fingerprint(destination))) != self.pairs[schema]:
            raise ValueError('Production database scope does not match pinned connection identities')
        return True

    def authorize_store(self,configuration,schema):
        self.require()
        if fingerprint(configuration) not in self.pairs.get(schema,frozenset()):
            raise ValueError('Store is outside the exact production database pairs')
        return True

    def close(self):
        self.closed = True
