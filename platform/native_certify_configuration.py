"""Native credential configuration and discovery over the retained SQL schema."""
import datetime
import json
import re
import uuid

import jwt
import psycopg2
from psycopg2.extras import Json
from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519

from native_keymanager import VaultFailure, certificate
from native_credential_proofs import algorithm as proof_algorithm, CredentialProofFailure


FIELDS = {
    'vcTemplate': 'vc_template', 'doctype': 'doctype', 'sdJwtVct': 'sd_jwt_vct',
    'credentialFormat': 'credential_format', 'didUrl': 'did_url', 'keyManagerAppId': 'key_manager_app_id',
    'keyManagerRefId': 'key_manager_ref_id', 'signatureAlgo': 'signature_algo',
    'signatureCryptoSuite': 'signature_crypto_suite', 'sdClaim': 'sd_claim', 'scope': 'scope',
    'qrSignatureAlgo': 'qr_signature_algo', 'metaDataDisplay': 'display', 'displayOrder': 'display_order',
    'credentialSubjectDefinition': 'credential_subject', 'sdJwtClaims': 'sd_jwt_claims',
    'msoMdocClaims': 'mso_mdoc_claims', 'pluginConfigurations': 'plugin_configurations',
    'credentialStatusPurposes': 'credential_status_purpose', 'qrSettings': 'qr_settings',
}
JSON_COLUMNS = {'display', 'credential_subject', 'sd_jwt_claims', 'mso_mdoc_claims', 'plugin_configurations', 'qr_settings', 'proof_types_supported'}


class CertifyConfiguration:
    def __init__(self, settings, engine):
        self.settings, self.engine = settings, engine

    def connect(self):
        return psycopg2.connect(**self.settings['connection'])

    def validate(self, body):
        if not isinstance(body, dict) or not isinstance(body.get('metaDataDisplay'), list):
            raise VaultFailure('Credential display metadata required')
        formats = ['ldp_vc', 'jwt_vc_json', 'jwt_vc_json-ld', 'vc+sd-jwt', 'mso_mdoc']
        if body.get('credentialFormat') not in formats:
            raise VaultFailure('Unsupported credential format')
        if not isinstance(body.get('scope'), str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', body['scope']):
            raise VaultFailure('A bounded credential scope is required')
        types = body.get('credentialTypes') or []
        contexts = body.get('contextURLs') or []
        if any(not isinstance(values, list) or any(not isinstance(value, str) or not value or ',' in value or len(value) > 2048 for value in values) for values in [types, contexts]):
            raise VaultFailure('Invalid credential type or context')
        if body['credentialFormat'] in ['ldp_vc', 'jwt_vc_json', 'jwt_vc_json-ld'] and not types:
            raise VaultFailure('Credential types required')
        if body['credentialFormat'] == 'mso_mdoc' and not body.get('doctype'):
            raise VaultFailure('Document type required')
        if body['credentialFormat'] == 'vc+sd-jwt' and not body.get('sdJwtVct'):
            raise VaultFailure('Selective-disclosure credential type required')
        if body.get('qrSettings') and (not isinstance(body['qrSettings'], list) or not body.get('vcTemplate')):
            raise VaultFailure('QR settings require a credential template and an entry list')
        plugins = body.get('pluginConfigurations')
        if plugins is not None and (not isinstance(plugins, list) or len(plugins) > 128 or any(
                not isinstance(item, dict) or len(item) > 128 or any(
                    not isinstance(k, str) or not isinstance(v, str) or not 1 <= len(k) <= 256 or len(v) > 16384
                    for k, v in item.items()) for item in plugins)):
            raise VaultFailure('Plugin configuration metadata requires a bounded list of string maps')
        app, ref = body.get('keyManagerAppId') or 'CERTIFY_VC_SIGN_RSA', body.get('keyManagerRefId') or ''
        self.engine.policy(app, ref)
        public = certificate(self.engine.get(app, ref)['certificate']).public_key()
        selected_algorithm = 'RS256' if isinstance(public, rsa.RSAPublicKey) else 'EdDSA' if isinstance(public, ed25519.Ed25519PublicKey) else {'secp256k1': 'ES256K', 'secp256r1': 'ES256'}.get(public.curve.name)
        if selected_algorithm is None or body.get('signatureAlgo') not in [None, selected_algorithm]:
            raise VaultFailure('Credential algorithm must match the selected signing key')
        suite = body.get('signatureCryptoSuite')
        if suite:
            try:
                if body['credentialFormat'] != 'ldp_vc' or proof_algorithm(public, suite) != selected_algorithm:
                    raise ValueError()
            except (ValueError, CredentialProofFailure):
                raise VaultFailure('Credential suite must match the selected signing key and format') from None
        for value in body.get('credentialStatusPurposes') or []:
            if value not in ['revocation', 'suspension']:
                raise VaultFailure('Unsupported credential status purpose')
        values = {column: body.get(name) for name, column in FIELDS.items()}
        values.update(context=','.join(contexts), credential_type=','.join(types),
                      key_manager_app_id=app, key_manager_ref_id=ref,
                      display_order=body.get('displayOrder') or [],
                      cryptographic_binding_methods_supported=['cose_key'] if body['credentialFormat'] == 'mso_mdoc' else ['did:jwk', 'did:key'],
                      credential_signing_alg_values_supported=[selected_algorithm],
                      proof_types_supported={'jwt': {'proof_signing_alg_values_supported': ['RS256', 'ES256', 'EdDSA']}},
                      status='active')
        if body['credentialFormat'] == 'mso_mdoc':
            values['proof_types_supported'] = {'cwt': {'proof_signing_alg_values_supported': [-7]}, 'jwt': {'proof_signing_alg_values_supported': ['ES256']}}
        if len(json.dumps(body)) > 1024 * 1024:
            raise VaultFailure('Credential configuration too large')
        return values

    def response(self, row):
        result = {name: row.get(column) for name, column in FIELDS.items()}
        result.update(credentialConfigKeyId=row['credential_config_key_id'],
                      credentialTypes=(row['credential_type'] or '').split(',') if row['credential_type'] else [],
                      contextURLs=(row['context'] or '').split(',') if row['context'] else [])
        return result

    def get(self, identifier):
        if not isinstance(identifier, str) or len(identifier) > 128:
            raise VaultFailure('Invalid configuration identifier')
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT row_to_json(t) FROM certify.credential_config t WHERE credential_config_key_id=%s', (identifier,))
            row = cursor.fetchone()
        if row is None:
            raise VaultFailure('Credential configuration not found')
        return row[0]

    def save(self, body, identifier=None):
        values = self.validate(body)
        identifier = identifier or body.get('credentialConfigKeyId') or str(uuid.uuid4())
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', identifier):
            raise VaultFailure('Invalid credential configuration identifier')
        values.update(credential_config_key_id=identifier, config_id=identifier)
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('credential-config:' + identifier,))
            now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            if self.settings.get('_update_requested'):
                raise VaultFailure('Invalid internal configuration')
            if body.get('_native_update'):
                raise VaultFailure('Reserved configuration field')
            cursor.execute('SELECT cr_dtimes FROM certify.credential_config WHERE credential_config_key_id=%s', (identifier,))
            previous = cursor.fetchone()
            if previous:
                raise VaultFailure('Configuration already exists')
            values.update(cr_dtimes=now, upd_dtimes=now)
            columns = list(values)
            parameters = [Json(values[name]) if name in JSON_COLUMNS and values[name] is not None else values[name] for name in columns]
            cursor.execute('INSERT INTO certify.credential_config (' + ','.join(columns) + ') VALUES (' + ','.join(['%s'] * len(columns)) + ')', parameters)
        return self.response(self.get(identifier))

    def update(self, identifier, body):
        values = self.validate(body)
        values['upd_dtimes'] = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('credential-config:' + identifier,))
            parameters = [Json(value) if column in JSON_COLUMNS and value is not None else value for column, value in values.items()]
            cursor.execute('UPDATE certify.credential_config SET ' + ','.join(column + '=%s' for column in values) + ' WHERE credential_config_key_id=%s', parameters + [identifier])
            if cursor.rowcount != 1:
                raise VaultFailure('Credential configuration not found')
        return self.response(self.get(identifier))

    def delete(self, identifier):
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('DELETE FROM certify.credential_config WHERE credential_config_key_id=%s', (identifier,))
            if cursor.rowcount != 1:
                raise VaultFailure('Credential configuration not found')
        return {'status': 'SUCCESS'}

    def jwks(self):
        keys = []
        with self.engine.vault.connect() as connection:
            rows = connection.execute('''SELECT k.*,t.certificate FROM vault_keys k
                JOIN km_certificates t ON k.id=t.key_id
                WHERE k.application!='ROOT' AND NOT EXISTS
                    (SELECT 1 FROM km_disabled d WHERE d.application=k.application AND d.reference=k.reference)
                AND ((k.state='ACTIVE' AND EXISTS (SELECT 1 FROM vault_aliases a WHERE a.key_id=k.id))
                    OR (k.state='VERIFY_ONLY' AND k.private_blob IS NOT NULL)) ORDER BY k.id''').fetchall()
        for row in rows:
            cert = certificate(row['certificate'])
            try:
                self.engine._valid(cert)
            except VaultFailure:
                continue
            public = cert.public_key()
            factory = jwt.algorithms.RSAAlgorithm if isinstance(public, rsa.RSAPublicKey) else jwt.algorithms.ECAlgorithm if isinstance(public, ec.EllipticCurvePublicKey) else jwt.algorithms.OKPAlgorithm
            key = json.loads(factory.to_jwk(public))
            key.update(kid=self.engine.jose_id(row), alg=row['algorithm'], use='sig')
            keys.append(key)
        return {'keys': keys}

    def did(self):
        issuer = self.settings['issuer']
        identifier = self.settings['did']
        verification = [{'id': identifier + '#' + key['kid'], 'type': 'JsonWebKey2020',
                         'controller': identifier, 'publicKeyJwk': key} for key in self.jwks()['keys']]
        return {'@context': ['https://www.w3.org/ns/did/v1', 'https://w3id.org/security/suites/jws-2020/v1'],
                'id': identifier, 'verificationMethod': verification,
                'assertionMethod': [key['id'] for key in verification]}

    def metadata(self, *, legacy=False):
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT row_to_json(t) FROM certify.credential_config t WHERE lower(status)='active'")
            rows = [row[0] for row in cursor.fetchall()]
        supported = {}
        for row in rows:
            supported[row['credential_config_key_id']] = {
                'format': row['credential_format'], 'scope': row['scope'], 'display': row['display'],
                'cryptographic_binding_methods_supported': row['cryptographic_binding_methods_supported'],
                'credential_signing_alg_values_supported': row['credential_signing_alg_values_supported'],
                'proof_types_supported': row['proof_types_supported'],
                'credential_definition': {'type': (row['credential_type'] or '').split(','),
                                         'credentialSubject': row['credential_subject'] or {}}}
            if row['credential_format'] == 'mso_mdoc':
                supported[row['credential_config_key_id']].pop('credential_definition')
                supported[row['credential_config_key_id']].update(doctype=row['doctype'], claims=row['mso_mdoc_claims'] or {})
            elif row['credential_format'] == 'vc+sd-jwt':
                supported[row['credential_config_key_id']].pop('credential_definition')
                supported[row['credential_config_key_id']].update(vct=row['sd_jwt_vct'], claims=row['sd_jwt_claims'] or {})
        issuer = self.settings['issuer']
        result = {'credential_issuer': issuer, 'credential_endpoint': issuer + '/v1/certify/issuance/credential',
                  'authorization_servers': [issuer], 'display': self.settings['display'],
                  'credential_configurations_supported': supported}
        if legacy:
            result['credentials_supported'] = supported
        return result

    def oauth_metadata(self):
        issuer = self.settings['issuer']
        return {'issuer': issuer, 'token_endpoint': issuer + '/v1/certify/oauth/token',
                'authorization_challenge_endpoint': issuer + '/v1/certify/oauth/iar',
                'jwks_uri': issuer + '/v1/certify/.well-known/jwks.json',
                'grant_types_supported': ['authorization_code', 'urn:ietf:params:oauth:grant-type:pre-authorized_code'],
                'response_types_supported': ['code'],
                'interactive_authorization_endpoint': issuer + '/v1/certify/oauth/iar',
                'code_challenge_methods_supported': ['S256'], 'token_endpoint_auth_methods_supported': ['none']}
