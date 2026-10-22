"""Native PKCE interactive authorization with pinned credential verification.

No caller-supplied URLs are fetched. Presentation signatures prove holder
control; issuer credentials must additionally verify against retained trust.
"""
import base64
import datetime
import hashlib
import json
import re
import secrets
import time

import jwt
from native_certify_authorization import CredentialAuthorizationFailure, digest, encode
from native_credential_holder import did_key


class CertifyInteractive:
    def __init__(self, issuance):
        self.issuance, self.authorization = issuance, issuance.authorization
        self.configuration = issuance.configuration

    @staticmethod
    def validate_submission(submission, definition_id, compact):
        """Bind the legacy JSON wrapper to the requested credential and format.

        Signature verification is performed separately by verify_presentation;
        unverified decoding here only checks descriptor/value consistency.
        """
        try:
            if not isinstance(compact,str) or len(compact)>512*1024:raise ValueError()
            if isinstance(submission,str):
                if len(submission)>65536:raise ValueError()
                submission=json.loads(submission)
            if (not isinstance(submission,dict) or set(submission)!={'id','definition_id','descriptor_map'}
                or submission['definition_id']!=definition_id or not isinstance(submission['id'],str)
                or not 1<=len(submission['id'])<=128):raise ValueError()
            credentials=jwt.decode(compact,options={'verify_signature':False})['vp']['verifiableCredential']
            if not isinstance(credentials,list) or len(credentials)!=1:raise ValueError()
            kind='jwt_vc_json' if isinstance(credentials[0],str) else 'ldp_vc'
            expected=[{'id':'trusted-beneficiary-credential','format':'jwt_vp','path':'$',
                       'path_nested':{'format':kind,'path':'$.vp.verifiableCredential[0]'}}]
            if submission['descriptor_map']!=expected:raise ValueError()
        except (ValueError,TypeError,KeyError,RecursionError,jwt.PyJWTError):
            raise CredentialAuthorizationFailure('invalid_presentation_submission') from None

    def trusted_keys(self, issuer, *, linked_data=False):
        """Issuer trust comes from protected configuration, never presentation URLs."""
        local = self.configuration.settings['did' if linked_data else 'issuer']
        if issuer == local:
            values = self.configuration.jwks()['keys']
        else:
            matches = [value for key, value in self.issuance.settings.get('trusted_issuers', {}).items()
                       if (value.get('did') if linked_data else key) == issuer]
            if len(matches) != 1:
                raise ValueError('Untrusted credential issuer')
            values = matches[0]['jwks']
        if not isinstance(values, list) or not 1 <= len(values) <= 32:
            raise ValueError('Invalid trusted issuer keys')
        result = {}
        for key in values:
            if not isinstance(key, dict) or any(name in key for name in ['d', 'p', 'q', 'dp', 'dq', 'qi', 'oth', 'k']):
                raise ValueError('Public verification keys required')
            if not isinstance(key.get('kid'), str) or key['kid'] in result:
                raise ValueError('Invalid trusted key identifier')
            result[key['kid']] = jwt.PyJWK.from_dict(key).key
        return result

    def verify_presentation(self, compact, nonce):
        try:
            if not isinstance(compact, str) or len(compact) > 512 * 1024:
                raise ValueError()
            header = jwt.get_unverified_header(compact)
            if header.get('typ') not in ['vp+jwt', 'JWT'] or header.get('crit') or any(key in header for key in ['jku', 'x5u', 'x5c']):
                raise ValueError()
            key = header.get('jwk')
            if key is not None and isinstance(header.get('kid'), str) and header['kid'].startswith('did:key:'):
                raise ValueError('Ambiguous holder key')
            if key is None and isinstance(header.get('kid'), str) and header['kid'].startswith('did:key:'):
                _, key = did_key(header['kid'])
            if not isinstance(key, dict):
                raise ValueError()
            if any(name in key for name in ['d', 'p', 'q', 'dp', 'dq', 'qi', 'oth', 'k']):
                raise ValueError()
            algorithm = {'RSA': 'RS256', 'EC': 'ES256', 'OKP': 'EdDSA'}[key['kty']]
            if header['alg'] != algorithm or key['kty'] == 'EC' and key.get('crv') != 'P-256' or key['kty'] == 'OKP' and key.get('crv') != 'Ed25519':
                raise ValueError()
            public = jwt.PyJWK.from_dict(key).key
            if key['kty'] == 'RSA' and public.key_size < 2048:
                raise ValueError()
            vp = jwt.decode(compact, public, algorithms=[algorithm], audience=self.configuration.settings['issuer'],
                            options={'require': ['exp', 'iat', 'iss', 'nonce', 'vp']})
            if vp['nonce'] != nonce or type(vp['iat']) not in [int, float] or type(vp['exp']) not in [int, float] or not time.time() - 300 <= vp['iat'] <= time.time() + 5 or vp['exp'] - vp['iat'] > 300:
                raise ValueError()
            credentials = vp['vp']['verifiableCredential']
            if not isinstance(credentials, list) or len(credentials) != 1:
                raise ValueError()
            credential = credentials[0]
            if isinstance(credential, str):
                unverified = jwt.decode(credential, options={'verify_signature': False})
                credential_issuer = unverified.get('iss')
                if not isinstance(credential_issuer, str):
                    raise ValueError()
                issuer_keys = self.trusted_keys(credential_issuer)
                signature = jwt.get_unverified_header(credential)
                if signature.get('alg') not in ['RS256', 'ES256', 'ES256K', 'EdDSA'] or signature.get('crit') or signature['kid'] not in issuer_keys:
                    raise ValueError()
                claims = jwt.decode(credential, issuer_keys[signature['kid']], algorithms=[signature['alg']],
                                    issuer=credential_issuer, options={'require': ['exp', 'iat', 'sub', 'vc']})
                subject = claims['vc']['credentialSubject']
                vc_issuer = claims['vc'].get('issuer')
                vc_issuer = vc_issuer.get('id') if isinstance(vc_issuer, dict) else vc_issuer
                if claims['sub'] != subject['id'] or vc_issuer not in [None, credential_issuer]:
                    raise ValueError()
                status = claims.get('credentialStatus') or claims['vc'].get('credentialStatus')
            else:
                credential_issuer = credential['issuer']
                credential_issuer = credential_issuer.get('id') if isinstance(credential_issuer, dict) else credential_issuer
                issuer_keys = self.trusted_keys(credential_issuer, linked_data=True)
                method = credential['proof']['verificationMethod']
                if not method.startswith(credential_issuer + '#'):
                    raise ValueError()
                self.issuance.proofs.verify(credential, issuer_keys[method.split('#')[-1]], method)
                expires = credential.get('validUntil') or credential.get('expirationDate')
                if not isinstance(expires, str) or datetime.datetime.fromisoformat(expires.replace('Z', '+00:00')).timestamp() <= time.time():
                    raise ValueError()
                subject, status = credential['credentialSubject'], credential.get('credentialStatus')
            holder = subject['id']
            if vp['iss'] != holder:
                raise ValueError()
            names = {'RSA': ['e', 'kty', 'n'], 'EC': ['crv', 'kty', 'x', 'y'], 'OKP': ['crv', 'kty', 'x']}[key['kty']]
            if holder.startswith('did:key:'):
                _, expected = did_key(holder)
                expected = {name: expected[name] for name in names}
            elif holder.startswith('did:jwk:'):
                encoded = holder.removeprefix('did:jwk:')
                expected = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
            else:
                raise ValueError()
            if expected != {name: key[name] for name in names}:
                raise ValueError()
            if status:
                self.issuance.status.verify_entries(status)
            return {name: value for name, value in subject.items() if name != 'id'}
        except CredentialAuthorizationFailure:
            raise
        except (ValueError, TypeError, KeyError, jwt.PyJWTError):
            raise CredentialAuthorizationFailure('invalid_presentation') from None

    def handle(self, body):
        if not isinstance(body, dict):
            raise CredentialAuthorizationFailure('invalid_request')
        if body.get('openid4vp_response') and body.get('openid4vp_presentation'):
            raise CredentialAuthorizationFailure('invalid_request')
        auth_session = body.get('auth_session')
        presentation = body.get('openid4vp_response') or body.get('openid4vp_presentation')
        if bool(auth_session) != bool(presentation):
            raise CredentialAuthorizationFailure('invalid_request')
        if not auth_session:
            client = body.get('client_id')
            challenge = body.get('code_challenge')
            details = body.get('authorization_details')
            if isinstance(details, str):
                details = json.loads(details)
            if body.get('response_type') != 'code' or not isinstance(client, str) or not 1 <= len(client) <= 256:
                raise CredentialAuthorizationFailure('invalid_request')
            if body.get('code_challenge_method') != 'S256' or not isinstance(challenge, str) or not re.fullmatch('[A-Za-z0-9_-]{43}', challenge):
                raise CredentialAuthorizationFailure('invalid_request')
            if not isinstance(details, list) or len(details) != 1 or details[0].get('type') != 'openid_credential':
                raise CredentialAuthorizationFailure('invalid_authorization_details')
            configuration = self.authorization.active_configuration(details[0].get('credential_configuration_id'))
            interaction = body.get('interaction_types_supported')
            if interaction and 'openid4vp_presentation' not in [value.strip() for value in interaction.split(',')]:
                raise CredentialAuthorizationFailure('missing_interaction_type')
            session, nonce = 'iar_session_' + secrets.token_urlsafe(36), secrets.token_urlsafe(32)
            payload = {'configuration': configuration['credential_config_key_id'], 'client_id': client,
                       'code_challenge': challenge, 'nonce': nonce, 'completed': False,
                       'auth_session': session, 'created_at': int(time.time()), 'authorization_details': details}
            issuers = [self.configuration.settings['issuer'], self.configuration.settings['did']]
            for issuer, trust in self.issuance.settings.get('trusted_issuers', {}).items():
                self.trusted_keys(issuer)
                issuers.append(issuer)
                if trust.get('did'):
                    self.trusted_keys(trust['did'], linked_data=True)
                    issuers.append(trust['did'])
            identifier = digest(session)
            with self.configuration.connect() as connection, connection.cursor() as cursor:
                cursor.execute('''INSERT INTO certify.iar_session(auth_session,transaction_id,verify_nonce,expires_at,client_id,scope,code_challenge,code_challenge_method,identity_data)
                                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                               (identifier, nonce, nonce, datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10),
                                client, configuration['scope'], challenge, 'S256', encode(self.authorization.seal(payload, identifier))))
            return {'status': 'require_interaction', 'type': 'openid4vp_presentation', 'auth_session': session, 'openid4vp_request': {
                'response_type': 'vp_token', 'client_id': self.configuration.settings['issuer'], 'nonce': nonce,
                'response_mode': 'direct_post', 'response_uri': self.configuration.settings['issuer'] + '/v1/certify/oauth/iar',
                'presentation_definition': {'id': configuration['credential_config_key_id'], 'input_descriptors': [
                    {'id': 'trusted-beneficiary-credential', 'format': {'jwt_vc_json': {'alg': ['RS256', 'ES256', 'EdDSA']}, 'ldp_vc': {'proof_type': ['RsaSignature2018']}},
                     'constraints': {'fields': [{'path': ['$.issuer', '$.issuer.id', '$.iss'], 'filter': {'type': 'string', 'enum': sorted(set(issuers))}}]}}]}}}
        identifier = digest(auth_session)
        with self.configuration.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT identity_data,expires_at,is_code_used FROM certify.iar_session WHERE auth_session=%s FOR UPDATE', (identifier,))
            row = cursor.fetchone()
            if row is None or row[1].replace(tzinfo=datetime.timezone.utc).timestamp() <= time.time() or row[2]:
                raise CredentialAuthorizationFailure('invalid_session')
            encrypted = base64.urlsafe_b64decode(row[0] + '=' * (-len(row[0]) % 4))
            payload = self.authorization.open(encrypted, identifier)
            if payload['completed']:
                raise CredentialAuthorizationFailure('invalid_session')
            if isinstance(presentation, str) and presentation.startswith('{'):
                wrapper=json.loads(presentation)
                if not isinstance(wrapper,dict) or set(wrapper)!={'vp_token','presentation_submission'}:
                    raise CredentialAuthorizationFailure('invalid_presentation_submission')
                self.validate_submission(wrapper['presentation_submission'],payload['configuration'],wrapper['vp_token'])
                presentation=wrapper['vp_token']
            claims = self.verify_presentation(presentation, payload['nonce'])
            code = 'iar_auth_' + secrets.token_urlsafe(36)
            code_id = digest(code)
            authorization = {'configuration': payload['configuration'], 'client_id': payload['client_id'],
                             'code_challenge': payload['code_challenge'], 'claims': claims, 'code': code,
                             'auth_session': auth_session, 'created_at': int(time.time())}
            cursor.execute('''INSERT INTO certify.native_authorization(id,kind,content,expires_at)
                              VALUES(%s,%s,%s,%s)''', (code_id, 'IAR', self.authorization.seal(authorization, code_id), int(time.time()) + 300))
            payload['completed'] = True
            payload['claims'], payload['code'] = claims, code
            cursor.execute('UPDATE certify.iar_session SET identity_data=%s,authorization_code=%s,code_issued_at=now() WHERE auth_session=%s',
                           (encode(self.authorization.seal(payload, identifier)), code_id, identifier))
            return {'status': 'ok', 'code': code}
