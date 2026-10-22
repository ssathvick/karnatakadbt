"""Native consent-scoped credential issuance with holder proof and nonce binding."""
import copy
import datetime
import hashlib
import hmac
import json
import secrets
import time
import uuid
from urllib.parse import quote

import httpx
import jwt

from native_auth_cache import AuthenticationFailure, b64, canonical
from native_credential_proofs import LinkedDataProofs


class CredentialIssuance:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings
        self.proofs = LinkedDataProofs(settings['contexts'])

    def metadata(self):
        return copy.deepcopy(self.settings['metadata'])

    def proof_key(self, value, nonce, client):
        try:
            if not isinstance(value, dict) or value.get('proof_type') != 'jwt':
                raise ValueError()
            compact = value['jwt']
            if not isinstance(compact, str) or len(compact) > 16384:
                raise ValueError()
            header = jwt.get_unverified_header(compact)
            if header.get('typ') != 'openid4vci-proof+jwt' or header.get('crit') or any(k in header for k in ['jku', 'x5u']):
                raise ValueError()
            key = header['jwk']
            if not isinstance(key, dict) or any(k in key for k in ['d', 'p', 'q', 'dp', 'dq', 'qi', 'oth', 'k']):
                raise ValueError()
            algorithms = {'RSA': ('RS256', ['e', 'kty', 'n']),
                          'EC': ('ES256', ['crv', 'kty', 'x', 'y']),
                          'OKP': ('EdDSA', ['crv', 'kty', 'x'])}
            algorithm, fields = algorithms[key['kty']]
            if header.get('alg') != algorithm:
                raise ValueError()
            if key['kty'] == 'EC' and key.get('crv') != 'P-256' or key['kty'] == 'OKP' and key.get('crv') != 'Ed25519':
                raise ValueError()
            public = jwt.PyJWK.from_dict(key, algorithm=algorithm).key
            if key['kty'] == 'RSA' and public.key_size < 2048:
                raise ValueError()
            claims = jwt.decode(compact, public, algorithms=[algorithm], audience=self.engine.settings['issuer'],
                                options={'require': ['aud', 'iat', 'nonce']})
            if claims.get('iss') not in [None, client] or not isinstance(claims['nonce'], str) or not hmac.compare_digest(claims['nonce'], nonce):
                raise ValueError()
            if not time.time() - 300 <= claims['iat'] <= time.time() + 5:
                raise ValueError()
            return 'did:jwk:' + b64(canonical({k: key[k] for k in sorted(fields)}))
        except (ValueError, TypeError, KeyError, jwt.PyJWTError):
            raise AuthenticationFailure('invalid_proof') from None

    def identity(self, transaction):
        individual = self.engine.cipher.decrypt(transaction['individualId'])
        try:
            with httpx.Client(trust_env=False, timeout=15) as client:
                response = client.get(self.engine.settings['identity_origin'] + '/v1/mock-identity-system/identity/' + quote(individual, safe=''),
                                      headers={'Authorization': 'Bearer ' + self.engine.settings['identity_service_token']})
                response.raise_for_status()
                value = response.json()
        except (httpx.HTTPError, ValueError):
            raise AuthenticationFailure('credential_issuance_unavailable') from None
        if value.get('errors') or not isinstance(value.get('response'), dict):
            raise AuthenticationFailure('credential_issuance_unavailable')
        return value['response']

    def issue(self, request, access_token):
        transaction = self.engine.access_transaction(access_token)
        grants = set(transaction['permittedScopes']) & set(transaction.get('requestedCredentialScopes') or [])
        definition = request.get('credential_definition')
        if not isinstance(definition, dict) or not isinstance(definition.get('type'), list):
            raise AuthenticationFailure('unsupported_credential_type')
        choices = [item for item in self.settings['metadata']['credentials_supported'].values()
                   if item['scope'] in grants and item['format'] == request.get('format')
                   and set(item['credential_definition']['type']) == set(definition['type'])]
        if len(choices) != 1:
            raise AuthenticationFailure('unsupported_credential_type')
        configuration = choices[0]
        if request.get('format') != 'ldp_vc':
            raise AuthenticationFailure('unsupported_credential_format')
        requested = definition.get('credentialSubject')
        supported = configuration['credential_definition']['credentialSubject']
        if requested is not None and (not isinstance(requested, dict) or not requested or set(requested) - set(supported)):
            raise AuthenticationFailure('invalid_credential_request')
        allowed_contexts = self.settings['contexts_for_credentials']
        if definition.get('@context') is not None and definition['@context'] != allowed_contexts:
            raise AuthenticationFailure('untrusted_credential_context')
        at_hash = transaction['aHash']
        nonce_key = self.engine.cache.key('vcissuance', at_hash)
        state = self.engine.cache.get('vcissuance', at_hash, required=False)
        if state is None:
            raise AuthenticationFailure('invalid_proof')
        nonce = state['cNonce']
        if not isinstance(nonce, str) or state['cNonceIssuedEpoch'] + state['cNonceExpireSeconds'] <= time.time():
            raise AuthenticationFailure('invalid_proof')
        try:
            holder = self.proof_key(request.get('proof'), nonce, transaction['clientId'])
        except AuthenticationFailure as error:
            error.payload = {'error': error.code, 'c_nonce': nonce,
                             'c_nonce_expires_in': max(0, self.engine.redis.ttl(nonce_key))}
            raise
        lock = 'kdbt-native-vci-issuance::' + at_hash
        marker = secrets.token_urlsafe(24)
        if not self.engine.redis.set(lock, marker, nx=True, ex=60):
            raise AuthenticationFailure('issuance_in_progress')
        try:
            if self.engine.cache.get('vcissuance', at_hash)['cNonce'] != nonce:
                raise AuthenticationFailure('invalid_proof')
            identity = self.identity(transaction)
            mapping = {'UIN': 'individualId', 'name': 'name', 'fullName': 'fullName', 'dateOfBirth': 'dateOfBirth',
                       'gender': 'gender', 'email': 'email', 'phone': 'phone', 'addressLine1': 'streetAddress',
                       'province': 'locality', 'region': 'region', 'postalCode': 'postalCode', 'face': 'encodedPhoto'}
            subject = {'id': holder}
            for name in requested or supported:
                if name in mapping and identity.get(mapping[name]) is not None:
                    subject[name] = identity[mapping[name]]
            now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
            document = {'@context': copy.deepcopy(allowed_contexts), 'id': 'urn:uuid:' + str(uuid.uuid4()),
                        'type': configuration['credential_definition']['type'], 'issuer': self.engine.settings['issuer'],
                        'issuanceDate': now, 'credentialSubject': subject}
            alias, private, certificate = self.engine.signing.key('OIDC_SERVICE')
            method = self.engine.settings['issuer'] + '/v1/esignet/oauth/.well-known/jwks.json#' + self.engine.signing.kid(alias, certificate)
            credential = self.proofs.sign(document, private, method, created=now)
            next_nonce = secrets.token_urlsafe(24)
            remaining = self.engine.redis.ttl(nonce_key)
            if remaining <= 0:
                raise AuthenticationFailure('invalid_proof')
            state.update(cNonce=next_nonce, cNonceIssuedEpoch=int(time.time()), cNonceExpireSeconds=remaining)
            self.engine.cache.update('vcissuance', at_hash, state, template='vci')
            return {'format': 'ldp_vc', 'credential': credential, 'c_nonce': next_nonce,
                    'c_nonce_expires_in': remaining}
        finally:
            self.engine.redis.eval("if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",
                                   1, lock, marker)
