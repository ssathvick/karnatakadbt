"""Native ledger searches and retained credential/template retrieval."""
import datetime
import json

from psycopg2.extras import Json
from native_keymanager import VaultFailure


class CertifyRecords:
    def __init__(self, configuration):
        self.configuration = configuration

    def search(self, body, *, version=1):
        if not isinstance(body, dict):
            raise VaultFailure('Search request required')
        for name in ['issuerId', 'credentialType']:
            if not isinstance(body.get(name), str) or not 0 < len(body[name]) <= 2048:
                raise VaultFailure('Issuer and credential type required')
        attributes = body.get('indexedAttributesEquals')
        if not isinstance(attributes, dict) or not attributes or len(attributes) > 64:
            raise VaultFailure('Indexed search criteria required')
        if any(not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip()
               or len(key) > 256 or len(value) > 4096 for key, value in attributes.items()):
            raise VaultFailure('Invalid indexed search criteria')
        clauses = ['issuer_id=%s', 'credential_type=%s', 'indexed_attributes @> %s::jsonb']
        parameters = [body['issuerId'], body['credentialType'], Json(attributes)]
        if body.get('credentialId'):
            if not isinstance(body['credentialId'], str) or len(body['credentialId']) > 2048:
                raise VaultFailure('Invalid credential identifier')
            clauses.append('credential_id=%s')
            parameters.append(body['credentialId'])
        with self.configuration.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT row_to_json(t) FROM certify.ledger t WHERE ' + ' AND '.join(clauses) + ' ORDER BY id', parameters)
            rows = [row[0] for row in cursor.fetchall()]
        results = []
        for row in rows:
            details = row['credential_status_details'] or [None]
            for detail in details:
                response = {'credentialId': row['credential_id'], 'issuerId': row['issuer_id'],
                            'credentialType': row['credential_type'], 'expirationDate': row['expiration_date'],
                            'issueDate': row['issuance_date'] if version == 1 else None,
                            'issuanceDate': row['issuance_date'] if version == 2 else None,
                            'statusListCredentialUrl': None, 'statusListIndex': None,
                            'statusPurpose': None, 'statusTimestamp': None}
                if detail:
                    response.update(statusListCredentialUrl=detail.get('statusListCredentialId'),
                                    statusListIndex=detail.get('statusListIndex'), statusPurpose=detail.get('statusPurpose'))
                    if detail.get('createdTimes') is not None:
                        response['statusTimestamp'] = datetime.datetime.fromtimestamp(
                            detail['createdTimes'] / 1000, datetime.timezone.utc).replace(tzinfo=None).isoformat()
                results.append(response)
        return results

    def retained(self, identifier, *, template=False):
        if not isinstance(identifier, str) or not 0 < len(identifier) <= 2048:
            raise VaultFailure('Invalid record identifier')
        # Table and column are fixed internal constants, never supplied by callers.
        table, column = ('rendering_template', 'template') if template else ('status_list_credential', 'vc_document')
        with self.configuration.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT ' + column + ' FROM certify.' + table + ' WHERE id=%s', (identifier,))
            row = cursor.fetchone()
        if row is None:
            raise VaultFailure('Record not found')
        if not template:
            try:
                json.loads(row[0])
            except ValueError:
                raise VaultFailure('Stored status document is invalid') from None
        return row[0]
