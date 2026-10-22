"""Candidate session authentication; no implicit role-to-permission escalation.

Production wiring must supply the console's authoritative permission resolver.
This adapter deliberately does not accept browser-supplied roles or JWT claims.
"""
import hmac
import json
import time

from registry_metadata_api import RegistryPrincipal


class RegistrySessionAuthorizer:
    def __init__(self, lookup, permission_resolver, origin, clock=time.time):
        self.lookup = lookup
        self.permission_resolver = permission_resolver
        self.origin = origin.rstrip('/')
        self.clock = clock

    def __call__(self, request):
        token = request.cookies.get('KA-INTAKE', '')
        if not token:
            return None
        # Query on every request so logout/deletion and expiry take effect without
        # an independent session cache. The lookup must be parameterized.
        session = self.lookup(token)
        if not session or session['expires'] <= self.clock():
            return None
        data = json.loads(session['data'])
        user = data.get('user') or {}
        subject = user.get('sub')
        if data.get('mode') != 'staff' or not isinstance(subject, str) or not subject:
            return None
        # All contract requests use POST, including reads. Enforce CSRF for all
        # of them; never assume a POST is harmless from its operation name.
        expected = data.get('csrf')
        supplied = request.headers.get('x-csrf-token', '')
        if not isinstance(expected, str) or not expected or not hmac.compare_digest(expected, supplied):
            return None
        if request.headers.get('origin', '').rstrip('/') != self.origin:
            return None
        permissions = self.permission_resolver(subject)
        if permissions is None:
            return None
        permissions = frozenset(permissions)
        if 'registryConfiguration:view' not in permissions:
            return None
        return RegistryPrincipal(subject, permissions)
