"""Issuer-controlled Sunbird credential-issuance wire adapter with pinned proofs."""
import copy
import json
import ssl
import time
from urllib.parse import urlsplit

import httpx
import jwt

from native_certify_authorization import CredentialAuthorizationFailure


class SunbirdIssuer:
    def __init__(self, settings):
        self.settings = settings

    def verify(self, document, credential, proofs):
        try:
            if not isinstance(credential, dict) or not isinstance(credential.get('proof'), dict):
                raise ValueError()
            if {key: value for key, value in credential.items() if key != 'proof'} != document:
                raise ValueError('External issuer altered protected credential content')
            method = credential['proof'].get('verificationMethod')
            public = self.settings['verification_keys'].get(method)
            if not isinstance(public, dict) or any(key in public for key in ['d', 'p', 'q', 'dp', 'dq', 'qi', 'oth', 'k']):
                raise ValueError()
            proofs.verify(credential, jwt.PyJWK.from_dict(public).key, method)
            return credential
        except (ValueError, KeyError, TypeError, jwt.PyJWTError):
            raise CredentialAuthorizationFailure('external_credential_verification_failed', status=503) from None

    def issue(self, document, proofs, *, idempotency_key):
        try:
            settings = self.settings
            endpoint = urlsplit(settings['url'])
            loopback = settings.get('allow_loopback_http_for_acceptance') is True and endpoint.hostname in ['127.0.0.1', '::1']
            if endpoint.scheme != 'https' and not (loopback and endpoint.scheme == 'http'):
                raise ValueError()
            if not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
                raise ValueError()
            if not isinstance(document, dict) or 'proof' in document or not isinstance(document.get('credentialSubject'), dict):
                raise ValueError()
            for name in ['schema_id', 'schema_version']:
                if not isinstance(settings[name], str) or not 0 < len(settings[name]) <= 256:
                    raise ValueError()
            headers = settings.get('headers', {})
            if not isinstance(headers, dict) or set(k.lower() for k in headers) - {'authorization', 'x-api-key'} or any(
                    not isinstance(v, str) or '\r' in v or '\n' in v for v in headers.values()):
                raise ValueError()
            if not isinstance(idempotency_key, str) or len(idempotency_key) != 64 or any(c not in '0123456789abcdef' for c in idempotency_key):
                raise ValueError()
            payload = {'credential': copy.deepcopy(document), 'credentialSchemaId': settings['schema_id'],
                       'credentialSchemaVersion': settings['schema_version'], 'tags': []}
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
            if len(body) > 512 * 1024:
                raise ValueError()
            headers = {**headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotency_key}
            with httpx.Client(trust_env=False, verify=ssl.create_default_context(cafile=settings.get('ca_file')),
                              timeout=5, follow_redirects=False) as client:
                with client.stream('POST', endpoint.geturl(), headers=headers, content=body) as response:
                    if not 200 <= response.status_code < 300:
                        raise ValueError()
                    raw, deadline = bytearray(), time.monotonic() + 5
                    for chunk in response.iter_bytes(chunk_size=65536):
                        raw.extend(chunk)
                        if len(raw) > 768 * 1024 or time.monotonic() > deadline:
                            raise ValueError()
            result = json.loads(raw)
            credential = result.get('credential') if isinstance(result, dict) else None
            return self.verify(document, credential, proofs)
        except (ValueError, KeyError, TypeError, OSError, httpx.HTTPError, jwt.PyJWTError):
            raise CredentialAuthorizationFailure('external_credential_issuance_unavailable', status=503) from None
