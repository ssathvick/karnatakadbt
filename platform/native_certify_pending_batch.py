"""Checkpointed projection of a complete, fenced interactive-session snapshot.

This covers Certify IAR rows and their verifier registrations, not unrelated
OAuth caches or credential journals. The caller retains the global fence until
all domain projections and recovery checks finish.
"""
import base64
import hashlib
import json
import os
import secrets
import time
import re
from pathlib import Path
from native_certify_iar_projection import retained_row,timestamp


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


class InteractiveBatchProjection:
    def __init__(self,folder,authorization,recovery,*,quiescent,callback_endpoint):
        self.folder=Path(folder).resolve(strict=True)
        base=Path('/opt/karnatakadbt/private/mosip-migration/remaining-three')
        if not self.folder.is_relative_to(base) or self.folder.stat().st_uid!=0 or self.folder.stat().st_mode&0o077:
            raise ValueError('Private root checkpoint directory required')
        if not re.fullmatch(r'http://native-certify-recovery\.nigeria\.svc\.cluster\.local:18154/[A-Za-z0-9_-]{48,128}/submit',callback_endpoint):
            raise ValueError('Pinned private production verifier route required')
        self.authorization,self.recovery=authorization,recovery
        self.quiescent,self.endpoint=quiescent,callback_endpoint
        self.path=self.folder/'interactive-batch.json'

    def require(self):
        if not callable(self.quiescent) or self.quiescent() is not True:
            raise ValueError('Observed global producer fence required')

    def save(self,state):
        temporary=self.folder/('batch-'+secrets.token_hex(12)+'.pending')
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:
            stream.write(canonical(state));stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,self.path)
        directory=os.open(self.folder,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)

    def prepare(self,rows):
        self.require()
        if not isinstance(rows,list) or len(rows)>10000 or len(canonical(rows))>32*1024*1024:
            raise ValueError('Bounded complete interactive snapshot required')
        rows=sorted(rows,key=lambda row:row['auth_session'])
        if len({r['auth_session'] for r in rows})!=len(rows):raise ValueError('Duplicate interactive identity')
        fingerprint=hashlib.sha256(canonical(rows)).hexdigest()
        if self.path.exists():
            info=self.path.lstat()
            if self.path.is_symlink() or info.st_uid!=0 or info.st_mode&0o077:raise ValueError('Unsafe batch checkpoint')
            state=json.loads(self.path.read_bytes())
            if state['source_sha256']!=fingerprint or state['endpoint_sha256']!=hashlib.sha256(self.endpoint.encode()).hexdigest():
                raise ValueError('Checkpoint source or callback route changed')
            return state
        plans=[]
        for row in rows:
            encrypted=row['identity_data'];identifier=row['auth_session']
            payload=self.authorization.open(base64.urlsafe_b64decode(encrypted+'='*(-len(encrypted)%4)),identifier)
            pending=payload.get('completed') is False
            projected=retained_row(row,self.authorization,presentation_recovered=pending)
            registration=None
            if pending and timestamp(row['expires_at'])>time.time():
                request_id,transaction_id=secrets.token_urlsafe(36),secrets.token_urlsafe(36)
                registration={'request_id':request_id,'transaction_id':transaction_id,'nonce':payload['nonce'],
                    'definition_id':payload['configuration'],'expires_at':int(timestamp(row['expires_at']))}
                projected.update(request_id=request_id,transaction_id=transaction_id,response_uri=self.endpoint)
            plans.append({'native':row,'retained':projected,'registration':registration})
        state={'version':1,'phase':'PREPARED','source_sha256':fingerprint,
            'endpoint_sha256':hashlib.sha256(self.endpoint.encode()).hexdigest(),'plans':plans}
        self.require();self.save(state);return state

    def register(self,state):
        self.require()
        for plan in state['plans']:
            values=plan['registration']
            if values:
                self.recovery.register(**values,idempotent=True)
                self.require()
        state={**state,'phase':'VERIFIER_READY'};self.save(state);return state

    def project(self,state,connection,*,production_scope=None,source=None,destination=None):
        """Convert already mirrored rows atomically; commit ACK loss is resumable.

        A complete table comparison prevents adopting a partial or stale batch.
        The caller must provide a separately authorised destination connection.
        """
        self.require()
        if connection.info.dbname=='inji_certify':
            from native_remaining_three_projection_scope import ProductionProjectionScope
            if not isinstance(production_scope,ProductionProjectionScope) or not source or not destination:
                raise ValueError('Pinned production projection scope required')
            production_scope.authorize(source,destination,'certify')
            if (connection.info.dbname,connection.info.host,connection.info.user)!=(destination['dbname'],destination['host'],destination['user']):
                raise ValueError('Destination connection differs from production scope')
        elif not connection.info.dbname.startswith(('kdbt_original_','kdbt_transfer_')):
            raise ValueError('Explicit recovery database required')
        if state['phase'] not in {'VERIFIER_READY','SQL_INTENT','PROJECTED'}:raise ValueError('Verifier checkpoint required')
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='5s'")
            cursor.execute('LOCK TABLE certify.iar_session IN ACCESS EXCLUSIVE MODE')
            cursor.execute('SELECT row_to_json(t) FROM certify.iar_session t')
            actual={row[0]['auth_session']:row[0] for row in cursor.fetchall()}
            expected={p['retained']['auth_session']:p['retained'] for p in state['plans']}
            source={p['native']['auth_session']:p['native'] for p in state['plans']}
            if actual==expected:
                self.require();state={**state,'phase':'PROJECTED'};self.save(state);return state
            if actual!=source:raise ValueError('Interactive batch differs from complete authoritative snapshot')
            self.require();state={**state,'phase':'SQL_INTENT'};self.save(state)
            for plan in state['plans']:
                row=plan['retained']
                cursor.execute('''UPDATE certify.iar_session SET auth_session=%s,authorization_code=%s,
                    identity_data=%s,transaction_id=%s,request_id=%s,response_uri=%s WHERE auth_session=%s''',
                    (row['auth_session'],row['authorization_code'],row['identity_data'],row['transaction_id'],row['request_id'],row['response_uri'],plan['native']['auth_session']))
                if cursor.rowcount!=1:raise ValueError('Interactive row changed during batch projection')
            cursor.execute('SELECT row_to_json(t) FROM certify.iar_session t')
            if {r[0]['auth_session']:r[0] for r in cursor.fetchall()}!=expected:raise ValueError('Projected interactive batch differs')
            self.require()
        connection.commit()
        state={**state,'phase':'PROJECTED'};self.save(state);return state
