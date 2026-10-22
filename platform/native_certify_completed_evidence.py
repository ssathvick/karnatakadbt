"""Recover completed claims from exact authenticated native session evidence.

Never trusts a plaintext identity column by itself. Both complete session
bindings and authenticated ciphertext must match the frozen retained record.
"""
import base64,hashlib,copy,json
import psycopg2
from native_certify_presentation_recovery import PresentationRecovery
from native_certify_iar_projection import retained_row,timestamp

class NativeCompletedEvidence(PresentationRecovery):
    def __init__(self,authorization,connection,recovery,*,fenced,scope=None,source=None,code_lifetime_seconds):
        if type(code_lifetime_seconds) is not int or not 1<=code_lifetime_seconds<=3600:raise ValueError('Pinned code lifetime required')
        if not connection['dbname'].startswith(('kdbt_original_','kdbt_transfer_')):
            from native_remaining_three_projection_scope import ProductionProjectionScope
            if not isinstance(scope,ProductionProjectionScope) or not source:raise ValueError('Pinned production pair required')
            scope.authorize(source,connection,'certify')
        self.native_authorization,self.connection,self.recovery=authorization,connection,recovery
        self.fenced,self.scope,self.source=fenced,scope,source
        self.code_lifetime_seconds=code_lifetime_seconds
        self.verified={}

    def require(self):
        if self.fenced() is not True:raise ValueError('Closed producer and worker fences required')
        if self.scope:self.scope.authorize(self.source,self.connection,'certify')

    def completed_claims(self,row,definition_id):
        self.require()
        binding=hashlib.sha256(json.dumps({'row':row,'definition':definition_id},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        # SQL mirroring replaces native row identities before atomic import.
        # Retain only claims already authenticated against the exact frozen
        # row, while this same coordinator continuously holds its fence.
        if binding in self.verified:return copy.deepcopy(self.verified[binding])
        if self.recovery is not None:
            try:return self.recovery.completed_claims(row,definition_id)
            except ValueError:pass
        identifier=hashlib.sha256(row['auth_session'].encode()).hexdigest()
        with psycopg2.connect(**self.connection) as connection,connection.cursor() as cursor:
            cursor.execute('SELECT row_to_json(t) FROM certify.iar_session t WHERE auth_session=%s FOR SHARE',(identifier,))
            found=cursor.fetchone()
        if found is None:raise ValueError('Authenticated native completion evidence missing')
        native=found[0]
        if retained_row(native,self.native_authorization)!=row:
            raise ValueError('Native completion differs from frozen retained bindings')
        encoded=native['identity_data']
        payload=self.native_authorization.open(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)),identifier)
        if (payload.get('completed') is not True or payload.get('configuration')!=definition_id
            or not isinstance(payload.get('claims'),dict) or payload['claims'].get('uin')!=row['identity_data']):
            raise ValueError('Authenticated native completion claims differ')
        expiry=min(timestamp(native['expires_at']),timestamp(native['code_issued_at'])+self.code_lifetime_seconds)
        self.require()
        result=(payload['claims'],expiry);self.verified[binding]=copy.deepcopy(result)
        return result
