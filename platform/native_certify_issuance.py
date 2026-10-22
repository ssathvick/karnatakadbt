"""Native issuance from protected pre-authorized claims with atomic nonce/ledger writes."""
import copy
import datetime
import hashlib
import json
import secrets
import time
import uuid

import jwt
from psycopg2.extras import Json
from native_certify_authorization import CredentialAuthorizationFailure, encode
from native_credential_holder import verify_holder
from native_credential_proofs import LinkedDataProofs, base58
from native_keymanager import VaultFailure
from native_certify_status import CertifyStatus, CONTEXT as STATUS_CONTEXT
from native_credential_mdoc import verify_cwt_holder, issue_mdoc
from native_credential_templates import CredentialTemplates
from native_certify_providers import CredentialProviders
from native_credential_qr import signed_entries
from native_certify_external_issuance import ExternalIssuance


class CertifyIssuance:
    def __init__(self, authorization, settings):
        self.authorization, self.configuration, self.crypto = authorization, authorization.configuration, authorization.crypto
        self.settings = settings
        self.proofs = LinkedDataProofs(settings['contexts'], settings.get('proof_runtime'))
        self.status = CertifyStatus(self)
        self.templates = CredentialTemplates(settings['templates']) if settings.get('templates') else None
        self.providers = CredentialProviders(settings.get('providers'))
        self.external = ExternalIssuance(self)

    def template(self, configuration, claims, values):
        if self.templates is None:
            raise CredentialAuthorizationFailure('template_runtime_unavailable')
        context = {**copy.deepcopy(claims), 'data': copy.deepcopy(claims),
                   'credentialSubject': copy.deepcopy(claims), **values,
                   '_issuer': configuration['did_url'] or self.configuration.settings['did'],
                   'didUrl': configuration['did_url'] or self.configuration.settings['did']}
        context['rootContext'] = copy.deepcopy(context)
        context['envConfigs'] = copy.deepcopy(self.settings.get('template_environment', {}))
        if 'id' in values:
            context['_holderId'] = values['id']
        for source, target in [('issuanceDate', 'validFrom'), ('expirationDate', 'validUntil')]:
            if source in values:
                context[target] = values[source]
        rendering_id = self.settings.get('rendering_template_id')
        if rendering_id and 'https://www.w3.org/ns/credentials/v2' in (configuration['context'] or '').split(','):
            with self.configuration.connect() as connection, connection.cursor() as cursor:
                cursor.execute('SELECT template FROM certify.rendering_template WHERE id=%s', (rendering_id,))
                row = cursor.fetchone()
            if row is None:
                raise CredentialAuthorizationFailure('rendering_template_unavailable')
            context['renderingTemplateId'] = rendering_id
            context['_renderMethodSVGdigest'] = 'z' + base58(hashlib.sha256(row[0].encode('utf-8')).digest())
        context['rootContext'] = copy.deepcopy({key: value for key, value in context.items() if key != 'rootContext'})
        if configuration['qr_settings']:
            context['claim_169_values'] = signed_entries(self, configuration, context)
        return self.templates.render(configuration['vc_template'], context)

    def sign_document(self, document, configuration):
        row, key, certificate = self.crypto.signing_key({'applicationId': configuration['key_manager_app_id'] or 'CERTIFY_VC_SIGN_RSA',
                                                       'referenceId': configuration['key_manager_ref_id'] or ''})
        method = (configuration.get('did_url') or self.configuration.settings['did']) + '#' + self.crypto.engine.jose_id(row)
        suite = configuration.get('signature_crypto_suite') or {
            'RS256': 'RsaSignature2018', 'EdDSA': 'Ed25519Signature2020',
            'ES256K': 'EcdsaSecp256k1Signature2019', 'ES256': 'JsonWebSignature2020'}.get(row['algorithm'])
        return self.proofs.sign(document, key, method, suite=suite)

    def issue(self, body, compact):
        session_id, access = self.authorization.access_session(compact)
        if not isinstance(body, dict):
            raise CredentialAuthorizationFailure('invalid_credential_request')
        with self.configuration.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT content,expires_at FROM certify.native_credential_session WHERE id=%s FOR UPDATE', (session_id,))
            row = cursor.fetchone()
            if row is None or row[1] <= time.time():
                raise CredentialAuthorizationFailure('invalid_token', status=401)
            session = self.authorization.open(row[0], session_id)
            if session.get('revoked_at') is not None:
                raise CredentialAuthorizationFailure('invalid_token',status=401)
            configuration = self.authorization.active_configuration(session['configuration'])
            if session.get('imported_original_cache') is True and session.get('client_id') is None:
                # The signed original token supplies the client binding that
                # its cached transaction omitted. Persist only with a valid
                # holder proof and the credential/nonce transaction below.
                session['client_id'] = access['client_id']
            row = (row[0], min(row[1], access['exp']))
            if configuration['scope'] != access['scope'] or session['client_id'] != access['client_id']:
                raise CredentialAuthorizationFailure('invalid_token', status=401)
            if configuration['credential_format'] != body.get('format'):
                raise CredentialAuthorizationFailure('unsupported_credential_format')
            supported = (configuration['credential_type'] or '').split(',')
            definition = body.get('credential_definition') or {}
            if body.get('format') in ['ldp_vc', 'jwt_vc_json', 'jwt_vc_json-ld'] and (not isinstance(definition, dict) or set(definition.get('type') or []) != set(supported)):
                raise CredentialAuthorizationFailure('unsupported_credential_type')
            if body.get('format') == 'vc+sd-jwt' and body.get('vct') != configuration['sd_jwt_vct']:
                raise CredentialAuthorizationFailure('unsupported_credential_type')
            if body.get('format') == 'mso_mdoc' and body.get('doctype') != configuration['doctype']:
                raise CredentialAuthorizationFailure('unsupported_credential_type')
            try:
                verifier = verify_cwt_holder if isinstance(body.get('proof'), dict) and body['proof'].get('proof_type') == 'cwt' else verify_holder
                holder, holder_key = verifier(body.get('proof'), session['nonce'], self.configuration.settings['issuer'], session['client_id'])
            except ValueError:
                raise CredentialAuthorizationFailure('invalid_proof', extra={'c_nonce': session['nonce'], 'c_nonce_expires_in': max(0, int(row[1] - time.time()))}) from None
            claims = self.providers.fetch(configuration, session['claims'])
            if any(name in claims for name in ['pin', 'password', 'individualBiometrics', 'private_key']):
                raise CredentialAuthorizationFailure('invalid_credential_claims')
            # A holder controls requests, never issuer-supplied identity attributes.
            if body.get('claims'):
                requested = body['claims']
                if not isinstance(requested, dict) or set(requested) - set(claims):
                    raise CredentialAuthorizationFailure('invalid_credential_request')
                claims = {name: claims[name] for name in requested}
            now = datetime.datetime.now(datetime.timezone.utc)
            expiry = now + datetime.timedelta(days=730)
            identifier = 'urn:uuid:' + str(uuid.uuid4())
            credential_format = body['format']
            contexts = [value for value in (configuration['context'] or '').split(',') if value] or ['https://www.w3.org/2018/credentials/v1']
            status_details, status_entries = self.status.allocate(cursor, configuration)
            if status_entries and STATUS_CONTEXT not in contexts:
                contexts.append(STATUS_CONTEXT)
            if credential_format == 'mso_mdoc':
                if status_entries:
                    raise CredentialAuthorizationFailure('unsupported_document_status')
                template = self.template(configuration, claims, {'credentialId': identifier, 'id': holder,
                    '_doctype': configuration['doctype'], 'issuanceDate': now.isoformat().replace('+00:00', 'Z'),
                    'expirationDate': expiry.isoformat().replace('+00:00', 'Z')}) if configuration['vc_template'] else None
                credential = issue_mdoc(configuration['doctype'], claims, holder_key, self.crypto, configuration, now, expiry, template=template)
            elif credential_format == 'ldp_vc':
                document = {'@context': contexts + [{'@vocab': 'https://localhost:8443/credentials#'}], 'id': identifier,
                            'type': supported, 'issuer': configuration['did_url'] or self.configuration.settings['did'],
                            'issuanceDate': now.isoformat().replace('+00:00', 'Z'), 'expirationDate': expiry.isoformat().replace('+00:00', 'Z'),
                            'credentialSubject': {**claims, 'id': holder}}
                if 'https://www.w3.org/ns/credentials/v2' in contexts:
                    document['validFrom'] = document.pop('issuanceDate')
                    document['validUntil'] = document.pop('expirationDate')
                if status_entries:
                    document['credentialStatus'] = status_entries[0] if len(status_entries) == 1 else status_entries
                if configuration['vc_template']:
                    document = self.template(configuration, claims, {'credentialId': identifier, 'id': holder,
                        'issuanceDate': now.isoformat().replace('+00:00', 'Z'), 'expirationDate': expiry.isoformat().replace('+00:00', 'Z'),
                        'credentialStatus': document.get('credentialStatus')})
                    issuer = document.get('issuer')
                    issuer = issuer.get('id') if isinstance(issuer, dict) else issuer
                    if not isinstance(document.get('credentialSubject'), dict) or issuer != (configuration['did_url'] or self.configuration.settings['did']):
                        raise CredentialAuthorizationFailure('invalid_credential_template')
                    if not set(supported) <= set(document.get('type') or []):
                        raise CredentialAuthorizationFailure('invalid_credential_template')
                    document['id'] = identifier
                    document['credentialSubject']['id'] = holder
                    if status_entries:
                        document['credentialStatus'] = status_entries[0] if len(status_entries) == 1 else status_entries
                credential = self.external.issue(configuration, document, session_id, session['nonce'], row[1])
                if credential is None:
                    credential = self.sign_document(document, configuration)
                else:
                    identifier = credential['id']
                    # A retry retains the original credential lifetime.
                    start = credential.get('issuanceDate') or credential.get('validFrom')
                    end = credential.get('expirationDate') or credential.get('validUntil')
                    if start:
                        now = datetime.datetime.fromisoformat(start.replace('Z', '+00:00'))
                    if end:
                        expiry = datetime.datetime.fromisoformat(end.replace('Z', '+00:00'))
            elif credential_format in ['jwt_vc_json', 'jwt_vc_json-ld', 'vc+sd-jwt']:
                signing_row, private, certificate = self.crypto.signing_key({'applicationId': configuration['key_manager_app_id'] or 'CERTIFY_VC_SIGN_RSA',
                                                                           'referenceId': configuration['key_manager_ref_id'] or ''})
                common = {'iss': self.configuration.settings['issuer'], 'sub': holder, 'iat': int(now.timestamp()),
                          'nbf': int(now.timestamp()), 'exp': int(expiry.timestamp()), 'jti': identifier, 'cnf': {'jwk': holder_key}}
                if status_entries:
                    common['credentialStatus'] = status_entries[0] if len(status_entries) == 1 else status_entries
                if configuration['vc_template']:
                    rendered = self.template(configuration, claims, {**common, 'credentialId': identifier,
                        'vct': configuration['sd_jwt_vct'], 'id': holder})
                    # The issuer/holder bindings and token lifetime come from
                    # verified state, independently of template substitution.
                    rendered.update(common)
                    common = rendered
                if credential_format == 'vc+sd-jwt':
                    protected = {'iss', 'sub', 'iat', 'nbf', 'exp', 'jti', 'cnf', 'vct', '_sd', '_sd_alg', 'credentialStatus'}
                    if set(claims) & protected:
                        raise CredentialAuthorizationFailure('invalid_credential_claims')
                    disclosed_claims = {name: common.get(name, value) for name, value in claims.items()}
                    selected = [name.strip() for name in configuration['sd_claim'].split(',') if name.strip()] if configuration['sd_claim'] else list(disclosed_claims)
                    if any(name not in disclosed_claims for name in selected):
                        raise CredentialAuthorizationFailure('invalid_selective_disclosure_claim')
                    common.update(disclosed_claims)
                    disclosures = []
                    for name in selected:
                        value = common.pop(name)
                        disclosures.append(encode(json.dumps([secrets.token_urlsafe(32), name, value], ensure_ascii=False, separators=(',', ':')).encode()))
                    common.update(vct=configuration['sd_jwt_vct'], _sd_alg='sha-256',
                                  _sd=sorted(encode(hashlib.sha256(value.encode()).digest()) for value in disclosures))
                    token = jwt.encode(common, private, algorithm=signing_row['algorithm'],
                                       headers={'kid': self.crypto.engine.jose_id(signing_row), 'typ': 'vc+sd-jwt'})
                    credential = token + '~' + '~'.join(disclosures) + '~'
                else:
                    if 'vc' not in common:
                        common['vc'] = {'@context': contexts, 'type': supported, 'credentialSubject': {**claims, 'id': holder}}
                    if not isinstance(common['vc'], dict) or not isinstance(common['vc'].get('credentialSubject'), dict) or not set(supported) <= set(common['vc'].get('type') or []):
                        raise CredentialAuthorizationFailure('invalid_credential_template')
                    common['vc']['credentialSubject']['id'] = holder
                    credential = jwt.encode(common, private, algorithm=signing_row['algorithm'],
                                            headers={'kid': self.crypto.engine.jose_id(signing_row), 'typ': 'JWT'})
            else:
                raise CredentialAuthorizationFailure('unsupported_credential_format')
            # The retained 0.14.0 binary stores pluginConfigurations as opaque
            # configuration metadata; its issuance providers do not consume it.
            # Preserve that metadata without treating administrative JSON as
            # authority to load code, select files, queries or remote endpoints.
            cursor.execute('''INSERT INTO certify.ledger(credential_id,issuer_id,issuance_date,expiration_date,credential_type,indexed_attributes,credential_status_details)
                              VALUES(%s,%s,%s,%s,%s,%s,%s)''',
                           (identifier, self.configuration.settings['issuer'], now.replace(tzinfo=None), expiry.replace(tzinfo=None),
                            configuration['credential_type'] or configuration['doctype'] or configuration['sd_jwt_vct'], Json(claims), Json(status_details)))
            session['nonce'] = secrets.token_urlsafe(32)
            session['nonce_issued_at'] = int(time.time())
            cursor.execute('UPDATE certify.native_credential_session SET content=%s,expires_at=%s WHERE id=%s',
                           (self.authorization.seal(session, session_id), row[1], session_id))
            return {'format': credential_format, 'credential': credential, 'c_nonce': session['nonce'],
                    'c_nonce_expires_in': max(0, int(row[1] - time.time()))}
