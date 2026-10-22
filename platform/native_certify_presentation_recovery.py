"""Durable, encrypted verification state for retained-process recovery.

This adapter is private recovery infrastructure. Its HTTP transport must be
loopback or authenticated; it must never be mounted on a public issuer route.
Only pre-registered transactions can be verified or read.
"""
import hashlib
import json
import re
import time

from native_certify_authorization import CredentialAuthorizationFailure, digest


class PresentationRecovery:
    def __init__(self, interactive):
        self.interactive = interactive
        self.authorization = interactive.authorization
        self.configuration = interactive.configuration

    def register(self, request_id, transaction_id, nonce, definition_id, expires_at, *, idempotent=False):
        if any(not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', value)
               for value in [request_id, transaction_id, nonce]):
            raise ValueError('Invalid recovery transaction')
        if not isinstance(definition_id, str) or not 1 <= len(definition_id) <= 128:
            raise ValueError('Invalid presentation definition')
        if type(expires_at) is not int or expires_at>time.time()+600 or (expires_at<=time.time() and not idempotent):
            raise ValueError('Invalid absolute recovery expiry')
        identifier = digest('vp-recovery:' + request_id)
        result_id = digest('vp-result:' + transaction_id)
        payload = {'request_id': request_id, 'transaction_id': transaction_id, 'nonce': nonce,
                   'definition_id': definition_id, 'verified': False}
        with self.configuration.connect() as connection, connection.cursor() as cursor:
            if idempotent:
                cursor.execute('SELECT id,kind,content,expires_at FROM certify.native_presentation_recovery WHERE id=ANY(%s) FOR UPDATE',([identifier,result_id],))
                existing={row[0]:row for row in cursor.fetchall()}
                if existing:
                    if set(existing)!={identifier,result_id}:raise ValueError('Incomplete verifier registration')
                    first,second=existing[identifier],existing[result_id]
                    opened=self.authorization.open(first[2],identifier)
                    expected={key:value for key,value in payload.items() if key!='verified'}
                    if (first[1]!='VP_RECOVERY' or second[1]!='VP_RECOVERY_INDEX' or first[3]!=expires_at or second[3]!=expires_at
                            or any(opened.get(k)!=v for k,v in expected.items())
                            or self.authorization.open(second[2],result_id)!={'request_id':request_id}):
                        raise ValueError('Verifier checkpoint identity or expiry differs')
                    return [identifier,result_id]
                if expires_at<=time.time():raise ValueError('Expired verifier registration cannot be recreated')
            cursor.execute('INSERT INTO certify.native_presentation_recovery(id,kind,content,expires_at) VALUES(%s,%s,%s,%s)',
                           (identifier, 'VP_RECOVERY', self.authorization.seal(payload, identifier), expires_at))
            cursor.execute('INSERT INTO certify.native_presentation_recovery(id,kind,content,expires_at) VALUES(%s,%s,%s,%s)',
                           (result_id, 'VP_RECOVERY_INDEX', self.authorization.seal({'request_id': request_id}, result_id), expires_at))
        return [identifier, result_id]

    def submit(self, request_id, compact, submission):
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', request_id):
            raise CredentialAuthorizationFailure('invalid_session')
        identifier = digest('vp-recovery:' + request_id)
        if not isinstance(compact, str) or len(compact) > 512 * 1024:
            raise CredentialAuthorizationFailure('invalid_presentation')
        fingerprint = hashlib.sha256(compact.encode()).hexdigest()
        if isinstance(submission, str):
            try:
                if len(submission) > 65536:
                    raise ValueError()
                submission = json.loads(submission)
            except (ValueError, RecursionError):
                raise CredentialAuthorizationFailure('invalid_presentation_submission') from None
        with self.configuration.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT content,expires_at FROM certify.native_presentation_recovery WHERE id=%s AND kind=%s FOR UPDATE',
                           (identifier, 'VP_RECOVERY'))
            row = cursor.fetchone()
            if row is None or row[1] <= time.time():
                raise CredentialAuthorizationFailure('invalid_session')
            state = self.authorization.open(row[0], identifier)
            if not isinstance(submission, dict) or set(submission) != {'id', 'definition_id', 'descriptor_map'} or not isinstance(submission.get('id'), str) or not 1 <= len(submission['id']) <= 128:
                raise CredentialAuthorizationFailure('invalid_presentation_submission')
            descriptors = submission['descriptor_map']
            nested = descriptors[0].get('path_nested') if isinstance(descriptors, list) and len(descriptors) == 1 and isinstance(descriptors[0], dict) else None
            nested_format = nested.get('format') if isinstance(nested, dict) else None
            expected = [{'id': 'trusted-beneficiary-credential', 'format': 'jwt_vp', 'path': '$',
                         'path_nested': {'format': nested_format, 'path': '$.vp.verifiableCredential[0]'}}]
            if nested_format not in ['jwt_vc_json', 'ldp_vc'] or submission.get('definition_id') != state['definition_id'] or descriptors != expected:
                raise CredentialAuthorizationFailure('invalid_presentation_submission')
            if state['verified']:
                if state['fingerprint'] != fingerprint:
                    raise CredentialAuthorizationFailure('invalid_session')
                return
            claims = self.interactive.verify_presentation(compact, state['nonce'])
            # The signature has already been checked above. This inspection
            # only confirms that the advertised descriptor matches its value.
            import jwt
            credential = jwt.decode(compact, options={'verify_signature': False})['vp']['verifiableCredential'][0]
            if nested_format != ('jwt_vc_json' if isinstance(credential, str) else 'ldp_vc'):
                raise CredentialAuthorizationFailure('invalid_presentation_submission')
            state.update(verified=True, fingerprint=fingerprint, claims=claims)
            cursor.execute('UPDATE certify.native_presentation_recovery SET content=%s WHERE id=%s',
                           (self.authorization.seal(state, identifier), identifier))

    def result(self, transaction_id):
        # Only random, pre-registered transaction identifiers are accepted. The
        # encrypted contents remain bounded to this private recovery database.
        if not isinstance(transaction_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', transaction_id):
            raise CredentialAuthorizationFailure('invalid_session')
        with self.configuration.connect() as connection, connection.cursor() as cursor:
            result_id = digest('vp-result:' + transaction_id)
            cursor.execute('SELECT content FROM certify.native_presentation_recovery WHERE id=%s AND kind=%s AND expires_at>%s',
                           (result_id, 'VP_RECOVERY_INDEX', int(time.time())))
            row = cursor.fetchone()
            if row is None:
                raise CredentialAuthorizationFailure('invalid_session')
            identifier = digest('vp-recovery:' + self.authorization.open(row[0], result_id)['request_id'])
            cursor.execute('SELECT content FROM certify.native_presentation_recovery WHERE id=%s AND kind=%s AND expires_at>%s',
                           (identifier, 'VP_RECOVERY', int(time.time())))
            row = cursor.fetchone()
            if row:
                state = self.authorization.open(row[0], identifier)
                if state['transaction_id'] != transaction_id:
                    raise CredentialAuthorizationFailure('invalid_session')
                if not state['verified']:
                    return {'vpResultStatus': 'PENDING'}
                return {'vpResultStatus': 'SUCCESS', 'vcResults': [
                    {'vc': json.dumps({'credentialSubject': state['claims']}, ensure_ascii=False)}]}
        raise CredentialAuthorizationFailure('invalid_session')

    def completed_claims(self, retained_row, definition_id):
        """Recover claims from our authenticated durable record, never raw SQL identity.

        Expired evidence may preserve a consumed tombstone. It cannot authorize
        a new code: callers must retain this record's absolute expiry.
        """
        request_id, transaction_id = retained_row.get('request_id'), retained_row.get('transaction_id')
        if any(not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',v)
               for v in [request_id,transaction_id]):
            raise ValueError('Bound verifier request and transaction required')
        identifier, index = digest('vp-recovery:'+request_id), digest('vp-result:'+transaction_id)
        with self.configuration.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT id,kind,content,expires_at FROM certify.native_presentation_recovery WHERE id=ANY(%s) FOR SHARE',([identifier,index],))
            rows={r[0]:r for r in cursor.fetchall()}
            if set(rows)!={identifier,index}:raise ValueError('Complete verifier evidence required')
            first,second=rows[identifier],rows[index]
            state=self.authorization.open(first[2],identifier)
            if (first[1]!='VP_RECOVERY' or second[1]!='VP_RECOVERY_INDEX' or first[3]!=second[3]
                or self.authorization.open(second[2],index)!={'request_id':request_id}
                or any(state.get(k)!=v for k,v in {'request_id':request_id,'transaction_id':transaction_id,
                    'nonce':retained_row.get('verify_nonce'),'definition_id':definition_id,'verified':True}.items())
                or not isinstance(state.get('claims'),dict) or not state['claims']
                or state['claims'].get('uin')!=retained_row.get('identity_data')):
                raise ValueError('Verified presentation binding differs from completed session')
            return state['claims'], first[3]
