"""Transactional status allocation, persistent update queue and native processor."""
import base64
import datetime
import gzip
import io
import json
import secrets
import re
import time
import uuid
from urllib.parse import urlsplit

from psycopg2.extras import Json
from native_certify_authorization import CredentialAuthorizationFailure, encode


CONTEXT = 'https://w3id.org/vc/status-list/2021/v1'
CAPACITY = 131072

def status_bytes(encoded, capacity):
    if not isinstance(encoded,str) or len(encoded)>4*1024*1024:
        raise CredentialAuthorizationFailure('invalid_status_list')
    # Retained BitstringStatusList publications use base64url multibase 'u'.
    value=encoded[1:] if encoded.startswith('u') else encoded
    try:
        raw=base64.b64decode(value+'='*(-len(value)%4),altchars=b'-_',validate=True)
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as source:
            bits=source.read(capacity//8+1)
    except (ValueError,OSError,EOFError):
        raise CredentialAuthorizationFailure('invalid_status_list') from None
    if len(bits)!=capacity//8:raise CredentialAuthorizationFailure('invalid_status_list')
    return bits


class CertifyStatus:
    def __init__(self, issuance):
        self.issuance, self.configuration = issuance, issuance.configuration

    def issuer_url(self, identifier):
        return self.configuration.settings['issuer'] + '/v1/certify/credentials/status-list/' + identifier

    def signing_configuration(self):
        return {'key_manager_app_id': 'CERTIFY_SERVICE', 'key_manager_ref_id': ''}

    def allocate(self, cursor, configuration):
        details, entries = [], []
        for purpose in configuration['credential_status_purpose'] or []:
            if purpose not in ['revocation', 'suspension']:
                raise CredentialAuthorizationFailure('unsupported_status_purpose')
            pool = 'native:' + configuration['credential_config_key_id']
            cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('certify-status:' + pool + ':' + purpose,))
            cursor.execute('''SELECT id,capacity FROM certify.status_list_credential WHERE credential_type=%s AND status_purpose=%s
                              ORDER BY cr_dtimes DESC FOR UPDATE''', (pool, purpose))
            available = cursor.fetchall()
            identifier, index = None, None
            for candidate, capacity in available:
                cursor.execute('SELECT count(*) FROM certify.status_list_available_indices WHERE status_list_credential_id=%s AND is_assigned', (candidate,))
                if cursor.fetchone()[0] >= capacity:
                    continue
                cursor.execute('''SELECT id,list_index FROM certify.status_list_available_indices
                                  WHERE status_list_credential_id=%s AND NOT is_assigned ORDER BY id LIMIT 1 FOR UPDATE''', (candidate,))
                retained = cursor.fetchone()
                if retained:
                    cursor.execute('UPDATE certify.status_list_available_indices SET is_assigned=true,upd_dtimes=now() WHERE id=%s', (retained[0],))
                    identifier, index = candidate, retained[1]
                    break
                for attempt in range(100):
                    proposed = secrets.randbelow(capacity)
                    cursor.execute('SELECT 1 FROM certify.status_list_available_indices WHERE status_list_credential_id=%s AND list_index=%s', (candidate, proposed))
                    if cursor.fetchone() is None:
                        identifier, index = candidate, proposed
                        break
                if identifier:
                    break
            if identifier is None:
                identifier, index = str(uuid.uuid4()), secrets.randbelow(CAPACITY)
                now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
                url = self.issuer_url(identifier)
                document = {'@context': ['https://www.w3.org/2018/credentials/v1', CONTEXT], 'id': url,
                            'type': ['VerifiableCredential', 'StatusList2021Credential'],
                            'issuer': self.configuration.settings['did'], 'issuanceDate': now,
                            'credentialSubject': {'id': url + '#list', 'type': 'StatusList2021', 'statusPurpose': purpose,
                                                  'encodedList': encode(gzip.compress(bytes(CAPACITY // 8), mtime=0))}}
                signed = self.issuance.sign_document(document, self.signing_configuration())
                cursor.execute('''INSERT INTO certify.status_list_credential(id,vc_document,credential_type,status_purpose,capacity,cr_dtimes)
                                  VALUES(%s,%s,%s,%s,%s,now())''', (identifier, json.dumps(signed), pool, purpose, CAPACITY))
            cursor.execute('''INSERT INTO certify.status_list_available_indices(status_list_credential_id,list_index,is_assigned,cr_dtimes)
                              SELECT %s,%s,true,now() WHERE NOT EXISTS(
                              SELECT 1 FROM certify.status_list_available_indices WHERE status_list_credential_id=%s AND list_index=%s)''',
                           (identifier, index, identifier, index))
            url = self.issuer_url(identifier)
            details.append({'statusListCredentialId': url, 'statusListIndex': index, 'statusPurpose': purpose, 'createdTimes': int(time.time() * 1000)})
            entries.append({'id': url + '#' + str(index), 'type': 'StatusList2021Entry', 'statusPurpose': purpose,
                            'statusListIndex': str(index), 'statusListCredential': url})
        return details, entries

    def list_identifier(self, url):
        prefix = self.issuer_url('')
        if not isinstance(url, str) or not url.startswith(prefix):
            raise CredentialAuthorizationFailure('invalid_status_list')
        identifier = url[len(prefix):]
        if not identifier or '/' in identifier or '?' in identifier or '#' in identifier or len(identifier) > 128:
            raise CredentialAuthorizationFailure('invalid_status_list')
        return identifier

    def stored_identifier(self, value):
        # Retained workers persist the list's primary key; older native
        # generations persisted its public URL. Both denote the same pool.
        if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}',value):
            return value
        return self.list_identifier(value)

    def verify_entries(self, entries):
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list) or not 1 <= len(entries) <= 8:
            raise CredentialAuthorizationFailure('invalid_presentation')
        for entry in entries:
            identifier = self.list_identifier(entry.get('statusListCredential'))
            index = entry.get('statusListIndex')
            if isinstance(index, str) and index.isdigit() and len(index) <= 10:
                index = int(index)
            if type(index) is not int or index < 0 or entry.get('type') not in {'StatusList2021Entry','BitstringStatusListEntry'}:
                raise CredentialAuthorizationFailure('invalid_presentation')
            with self.configuration.connect() as connection, connection.cursor() as cursor:
                cursor.execute('SELECT vc_document,capacity,status_purpose FROM certify.status_list_credential WHERE id=%s', (identifier,))
                row = cursor.fetchone()
                if row is None or index >= row[1] or row[1] > 8 * 1024 * 1024 or entry.get('statusPurpose') != row[2]:
                    raise CredentialAuthorizationFailure('invalid_presentation')
                cursor.execute('''SELECT status_value FROM certify.credential_status_transaction
                                  WHERE status_list_credential_id IN (%s,%s) AND status_list_index=%s
                                  ORDER BY transaction_log_id DESC LIMIT 1''', (identifier,self.issuer_url(identifier), index))
                pending = cursor.fetchone()
            document = json.loads(row[0])
            method = document['proof']['verificationMethod']
            if not method.startswith(self.configuration.settings['did'] + '#'):
                raise CredentialAuthorizationFailure('invalid_presentation')
            import jwt
            key = next(key for key in self.configuration.jwks()['keys'] if key['kid'] == method.split('#')[-1])
            self.issuance.proofs.verify(document, jwt.PyJWK.from_dict(key).key, method)
            subject = document['credentialSubject']
            if subject['statusPurpose'] != row[2] or document['id'] != self.issuer_url(identifier):
                raise CredentialAuthorizationFailure('invalid_presentation')
            encoded = subject['encodedList']
            bits=status_bytes(encoded,row[1])
            revoked = bool(bits[index // 8] & (1 << (7 - index % 8)))
            # A committed update takes effect immediately, even before the
            # publication worker has regenerated the public signed list.
            if pending is not None:
                revoked = pending[0]
            if revoked:
                raise CredentialAuthorizationFailure('credential_status_rejected')

    def update(self, body, *, version=1):
        if not isinstance(body, dict) or type(body.get('status')) is not bool or not isinstance(body.get('credentialStatus'), dict):
            raise CredentialAuthorizationFailure('invalid_request')
        status = body['credentialStatus']
        purpose, index = status.get('statusPurpose'), status.get('statusListIndex')
        if purpose not in [None, 'revocation', 'suspension'] or type(index) is not int or index < 0:
            raise CredentialAuthorizationFailure('invalid_request')
        identifier = self.list_identifier(status.get('statusListCredential'))
        credential = body.get('credentialId')
        with self.configuration.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT capacity,status_purpose FROM certify.status_list_credential WHERE id=%s FOR UPDATE', (identifier,))
            row = cursor.fetchone()
            if row is None or index >= row[0] or purpose not in [None, row[1]]:
                raise CredentialAuthorizationFailure('invalid_status_list')
            purpose = row[1]
            cursor.execute('''SELECT is_assigned FROM certify.status_list_available_indices WHERE status_list_credential_id=%s AND list_index=%s''', (identifier, index))
            assigned = cursor.fetchone()
            if assigned is None or not assigned[0]:
                raise CredentialAuthorizationFailure('unassigned_status_index')
            ledger = None
            if version == 1:
                cursor.execute('SELECT row_to_json(t) FROM certify.ledger t WHERE credential_id=%s', (credential,))
                result = cursor.fetchone()
                if result is None:
                    raise CredentialAuthorizationFailure('credential_not_found', status=404)
                ledger = result[0]
                if not any(detail.get('statusListCredentialId') == self.issuer_url(identifier) and detail.get('statusListIndex') == index
                           for detail in ledger['credential_status_details'] or []):
                    raise CredentialAuthorizationFailure('credential_status_mismatch')
            now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            cursor.execute('''INSERT INTO certify.credential_status_transaction(credential_id,status_purpose,status_value,status_list_credential_id,status_list_index,cr_dtimes,is_processed)
                              VALUES(%s,%s,%s,%s,%s,%s,false)''', (credential, purpose, body['status'], identifier, index, now))
            response = {'statusListCredentialUrl': self.issuer_url(identifier), 'statusListIndex': index,
                        'statusPurpose': purpose, 'statusTimestamp': now.isoformat()}
            if ledger:
                response.update(credentialId=credential, issuerId=ledger['issuer_id'], credentialType=ledger['credential_type'],
                                issueDate=ledger['issuance_date'], expirationDate=ledger['expiration_date'])
            return response

    def process(self, limit=100, *, admitted=None):
        processed = 0
        for attempt in range(limit):
            if admitted:admitted()
            with self.configuration.connect() as connection, connection.cursor() as cursor:
                # A single advisory processor lock preserves transaction order
                # even when duplicate timers or manual processors overlap.
                cursor.execute("SELECT pg_try_advisory_xact_lock(hashtext('native-certify-status-processor'))")
                if not cursor.fetchone()[0]:
                    break
                cursor.execute('''SELECT transaction_log_id,status_list_credential_id,status_list_index,status_value,status_purpose
                                  FROM certify.credential_status_transaction WHERE NOT is_processed ORDER BY transaction_log_id LIMIT 1 FOR UPDATE''')
                transaction = cursor.fetchone()
                if transaction is None:
                    break
                transaction_id, url, index, value, purpose = transaction
                identifier = self.stored_identifier(url)
                cursor.execute('SELECT vc_document,capacity FROM certify.status_list_credential WHERE id=%s FOR UPDATE', (identifier,))
                row = cursor.fetchone()
                if row is None or not 0 <= index < row[1] or row[1] > 8 * 1024 * 1024:
                    raise ValueError('Invalid retained status transaction')
                document = json.loads(row[0])
                proof = document['proof']
                key_id = proof['verificationMethod'].split('#')[-1]
                key = next(key for key in self.configuration.jwks()['keys'] if key['kid'] == key_id)
                import jwt
                self.issuance.proofs.verify(document, jwt.PyJWK.from_dict(key).key, proof['verificationMethod'])
                subject = document['credentialSubject']
                if subject['statusPurpose'] != purpose:
                    raise ValueError('Status purpose mismatch')
                encoded = subject['encodedList']
                bits=bytearray(status_bytes(encoded,row[1]))
                mask = 1 << (7 - index % 8)
                if value:
                    bits[index // 8] |= mask
                else:
                    bits[index // 8] &= ~mask
                subject['encodedList'] = ('u' if encoded.startswith('u') else '')+encode(gzip.compress(bytes(bits), mtime=0))
                document.pop('proof')
                signed = self.issuance.sign_document(document, self.signing_configuration())
                cursor.execute('UPDATE certify.status_list_credential SET vc_document=%s,upd_dtimes=now() WHERE id=%s', (json.dumps(signed), identifier))
                cursor.execute('UPDATE certify.credential_status_transaction SET is_processed=true,processed_dtimes=now() WHERE transaction_log_id=%s', (transaction_id,))
                if admitted:admitted()
                processed += 1
        return processed
