"""Fenced, checkpointed legacy IAR import into encrypted native state.

Production destinations require the exact closed projection scope. Completed
sessions additionally require authenticated verifier evidence and their code
journal in the same SQL transaction. This grants no writer admission or owner.
"""
import base64
import hashlib
import re
import time
from native_certify_pending_batch import InteractiveBatchProjection, canonical
from native_certify_iar_projection import timestamp, retained_row


def completed_native_plan(row, configurations, authorization, recovery, *, code_lifetime_seconds):
    """Convert a completed original row using authenticated verifier evidence.

    The caller supplies the inspected original runtime's code lifetime; this
    function never infers it from the native defaults or resets issue time.
    """
    from native_certify_presentation_recovery import PresentationRecovery
    if not isinstance(recovery,PresentationRecovery):raise ValueError('Authenticated verifier store required')
    if type(code_lifetime_seconds) is not int or not 1<=code_lifetime_seconds<=3600:
        raise ValueError('Pinned original code lifetime required')
    code=row.get('authorization_code')
    if not isinstance(code,str) or not 1<=len(code)<=4096 or type(row.get('is_code_used')) is not bool:
        raise ValueError('Completed authorization state required')
    issued=timestamp(row['code_issued_at']); used=row.get('code_used_at')
    if issued>time.time()+5 or (row['is_code_used'] != (used is not None)):
        raise ValueError('Inconsistent completed code timestamps')
    if used is not None and not issued<=timestamp(used)<=time.time()+5:
        raise ValueError('Invalid consumed code chronology')
    # Reuse the binding validation without accepting a renewed source deadline.
    pending={**row,'authorization_code':None,'identity_data':None,'is_code_used':False,'code_issued_at':None,'code_used_at':None}
    native=_pending_native_row(pending,configurations,authorization,allow_expired=row['is_code_used'])
    payload=authorization.open(base64.urlsafe_b64decode(native['identity_data']+'='*(-len(native['identity_data'])%4)),native['auth_session'])
    claims,proof_expiry=recovery.completed_claims(row,payload['configuration'])
    expiry=min(timestamp(row['expires_at']),issued+code_lifetime_seconds,proof_expiry)
    if not row['is_code_used'] and expiry<=time.time():raise ValueError('Completed authorization already expired')
    payload.update(completed=True,claims=claims,code=code)
    native={**row,'auth_session':native['auth_session'],'authorization_code':hashlib.sha256(code.encode()).hexdigest(),
            'identity_data':base64.urlsafe_b64encode(authorization.seal(payload,native['auth_session'])).decode().rstrip('=')}
    if retained_row(native,authorization)!=row:raise ValueError('Completed import lost an original binding')
    journal={'id':native['authorization_code'],'kind':'IAR','content':authorization.seal(payload,native['authorization_code']),
             'expires_at':int(expiry),'used_at':int(timestamp(used)) if used else None}
    return {'retained':row,'native':native,'journal':journal}


def pending_native_row(row, configurations, authorization):
    return _pending_native_row(row,configurations,authorization,allow_expired=False)


def _pending_native_row(row, configurations, authorization, *, allow_expired):
    if (row.get('authorization_code') is not None or row.get('identity_data') is not None
            or row.get('is_code_used') is not False or row.get('code_issued_at') is not None
            or row.get('code_used_at') is not None):
        raise ValueError('Only uncompleted pending sessions can be imported')
    required = ['auth_session', 'client_id', 'verify_nonce', 'scope']
    if any(not isinstance(row.get(k), str) or not 1 <= len(row[k]) <= 4096 for k in required):
        raise ValueError('Bounded original interactive bindings required')
    if row.get('code_challenge_method') != 'S256' or not re.fullmatch(r'[A-Za-z0-9_-]{43}', row.get('code_challenge') or ''):
        raise ValueError('Supported PKCE binding required')
    # Never pick the first configuration when several programmes share a scope.
    matches = [c for c in configurations if c.get('scope') == row['scope']
               and str(c.get('status')).lower() == 'active']
    if len(matches) != 1:
        raise ValueError('Exactly one active configuration must match the original scope')
    configuration = matches[0]['credential_config_key_id']
    expires = timestamp(row['expires_at'])
    if expires <= time.time() and not allow_expired:
        raise ValueError('Expired pending session cannot be imported or renewed')
    raw = row['auth_session']; identifier = hashlib.sha256(raw.encode()).hexdigest()
    payload = {'configuration': configuration, 'client_id': row['client_id'],
               'code_challenge': row['code_challenge'], 'nonce': row['verify_nonce'],
               'completed': False, 'auth_session': raw,
               'authorization_details': [{'type': 'openid_credential', 'credential_configuration_id': configuration}]}
    encrypted = base64.urlsafe_b64encode(authorization.seal(payload, identifier)).decode().rstrip('=')
    native = {**row, 'auth_session': identifier, 'identity_data': encrypted}
    if retained_row(native, authorization, presentation_recovered=True) != row:
        raise ValueError('Pending import lost an original binding')
    return native


class PendingInteractiveImport(InteractiveBatchProjection):
    """Reuses the private durable checkpoint mechanics, not reverse projection.

    The caller first mirrors its complete frozen source into the destination;
    this converts that snapshot atomically, without changing the source DB.
    """
    def prepare_import(self, rows, configurations):
        self.require()
        if not isinstance(rows, list) or len(rows) > 10000 or len(canonical(rows)) > 32 * 1024 * 1024:
            raise ValueError('Bounded complete pending snapshot required')
        rows = sorted(rows, key=lambda r: r['auth_session'])
        if len({r['auth_session'] for r in rows}) != len(rows):
            raise ValueError('Duplicate pending session')
        fingerprint = hashlib.sha256(canonical({'rows': rows, 'configurations': configurations,'policy':self.policy()})).hexdigest()
        if self.path.exists():
            info = self.path.lstat()
            if self.path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o077:
                raise ValueError('Unsafe import checkpoint')
            import json
            state = json.loads(self.path.read_bytes())
            if state.get('direction') != 'LEGACY_PENDING_TO_NATIVE' or state['source_sha256'] != fingerprint:
                raise ValueError('Pending import checkpoint changed')
            return state
        plans = [self.plan(r,configurations) for r in rows]
        state = {'version': 1, 'direction': 'LEGACY_PENDING_TO_NATIVE', 'phase': 'PREPARED',
                 'source_sha256': fingerprint, 'plans': plans}
        self.save(state)
        return state

    def policy(self):return {}

    def plan(self,row,configurations):
        return {'retained':row,'native':pending_native_row(row,configurations,self.authorization)}

    def validate_evidence(self,state):pass

    def import_pending(self, state, connection, *, production_scope=None, source=None, destination=None):
        if production_scope is not None:
            from native_remaining_three_projection_scope import ProductionProjectionScope
            if (not isinstance(production_scope,ProductionProjectionScope) or not source or not destination
                    or source['dbname']!='inji_certify' or not destination['dbname'].startswith('kdbt_native_certify_')):
                raise ValueError('Pinned production forward import scope required')
            production_scope.authorize(source,destination,'certify')
            import psycopg2
            with psycopg2.connect(**source) as frozen, frozen.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout='5s'")
                cursor.execute('LOCK TABLE certify.iar_session IN SHARE MODE')
                cursor.execute('SELECT row_to_json(t) FROM certify.iar_session t')
                actual={r[0]['auth_session']:r[0] for r in cursor.fetchall()}
                if actual!={p['retained']['auth_session']:p['retained'] for p in state['plans']}:
                    raise ValueError('Authoritative production source changed since checkpoint')
                return self._import_pending_locked(state,connection,production_scope=production_scope,source=source,destination=destination)
        return self._import_pending_locked(state,connection)

    def _import_pending_locked(self, state, connection, *, production_scope=None, source=None, destination=None):
        self.require()
        if not connection.info.dbname.startswith(('kdbt_original_', 'kdbt_transfer_')):
            from native_remaining_three_projection_scope import ProductionProjectionScope
            if (not isinstance(production_scope,ProductionProjectionScope) or not source or not destination
                or source['dbname']!='inji_certify' or not destination['dbname'].startswith('kdbt_native_certify_')):
                raise ValueError('Exact retained-to-native production import scope required')
            production_scope.authorize(source,destination,'certify')
            if (connection.info.dbname,connection.info.host,connection.info.user)!=(destination['dbname'],destination['host'],destination['user']):
                raise ValueError('Production import connection differs')
        # Reload the durable checkpoint; callers cannot supply altered plans.
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='5s'")
            cursor.execute('LOCK TABLE certify.credential_config IN SHARE MODE')
        state = self.prepare_import([p['retained'] for p in state['plans']], self.configurations(connection))
        self.validate_evidence(state)
        if state['phase'] not in {'PREPARED', 'SQL_INTENT', 'PROJECTED'}:
            raise ValueError('Invalid pending import phase')
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='5s'")
            cursor.execute('LOCK TABLE certify.iar_session IN ACCESS EXCLUSIVE MODE')
            cursor.execute('LOCK TABLE certify.native_authorization IN SHARE ROW EXCLUSIVE MODE')
            cursor.execute('SELECT row_to_json(t) FROM certify.iar_session t')
            actual = {r[0]['auth_session']: r[0] for r in cursor.fetchall()}
            expected = {p['native']['auth_session']: p['native'] for p in state['plans']}
            original = {p['retained']['auth_session']: p['retained'] for p in state['plans']}
            journals=[{**p['journal'],'content':base64.b64decode(p['journal']['content'],validate=True)}
                      for p in state['plans'] if p.get('journal')]
            for journal in journals:
                cursor.execute('SELECT kind,content,expires_at,used_at,attempts FROM certify.native_authorization WHERE id=%s',(journal['id'],))
                existing=cursor.fetchone()
                if existing:
                    previous=self.authorization.open(existing[1],journal['id'])
                    imported=self.authorization.open(journal['content'],journal['id'])
                    immutable=('configuration','client_id','code_challenge','claims','code','auth_session')
                    if (existing[0]!=journal['kind'] or type(existing[4]) is not int or not 0<=existing[4]<=5
                        or any(key not in previous or previous[key]!=imported.get(key) for key in immutable)
                        or (existing[3] is not None and journal['used_at'] is None)):
                        raise ValueError('Existing code journal differs; consumption cannot be overwritten')
                    # Authenticated source evidence may add its full interactive
                    # binding to the older compact journal. Keep the earliest
                    # deadline, existing consumption and every failed attempt.
                    cursor.execute('''UPDATE certify.native_authorization SET content=%s,
                        expires_at=least(expires_at,%s),used_at=coalesce(used_at,%s) WHERE id=%s''',
                        (journal['content'],journal['expires_at'],journal['used_at'],journal['id']))
            if actual == expected:
                for journal in journals:
                    cursor.execute('SELECT 1 FROM certify.native_authorization WHERE id=%s',(journal['id'],))
                    if cursor.fetchone() is None:raise ValueError('Committed completed session lacks code journal')
                self.require(); state = {**state, 'phase': 'PROJECTED'}; self.save(state); return state
            if actual != original:
                raise ValueError('Complete destination differs from frozen pending source')
            if any(j['used_at'] is None and j['expires_at']<=time.time() for j in journals):
                raise ValueError('Completed code expired before import')
            # An ACK retry can recognize an already imported expired row, but
            # cannot newly import it or reset its original absolute deadline.
            if any(timestamp(r['expires_at']) <= time.time() and not r['is_code_used']
                   and (r.get('authorization_code') is not None or not getattr(self,'preserve_expired_pending',False)) for r in original.values()):
                raise ValueError('Pending source expired before import')
            self.require(); state = {**state, 'phase': 'SQL_INTENT'}; self.save(state)
            for plan in state['plans']:
                cursor.execute('UPDATE certify.iar_session SET auth_session=%s,identity_data=%s,authorization_code=%s WHERE auth_session=%s',
                               (plan['native']['auth_session'], plan['native']['identity_data'],plan['native']['authorization_code'], plan['retained']['auth_session']))
                if cursor.rowcount != 1:
                    raise ValueError('Pending source changed')
            for journal in journals:
                cursor.execute('INSERT INTO certify.native_authorization(id,kind,content,expires_at,used_at) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING',
                    (journal['id'],journal['kind'],journal['content'],journal['expires_at'],journal['used_at']))
            cursor.execute('SELECT row_to_json(t) FROM certify.iar_session t')
            if {r[0]['auth_session']: r[0] for r in cursor.fetchall()} != expected:
                raise ValueError('Pending import lost state')
            self.require()
            if production_scope is not None:production_scope.require()
        connection.commit()
        state = {**state, 'phase': 'PROJECTED'}; self.save(state); return state

    @staticmethod
    def configurations(connection):
        with connection.cursor() as cursor:
            cursor.execute('SELECT row_to_json(t) FROM certify.credential_config t ORDER BY credential_config_key_id')
            return [r[0] for r in cursor.fetchall()]


class InteractiveStateImport(PendingInteractiveImport):
    def __init__(self,*args,code_lifetime_seconds,preserve_expired_pending=False,**kwargs):
        super().__init__(*args,**kwargs)
        self.code_lifetime_seconds=code_lifetime_seconds
        if type(preserve_expired_pending) is not bool:raise ValueError('Explicit archival-expiry policy required')
        self.preserve_expired_pending=preserve_expired_pending

    def policy(self):
        result={'code_lifetime_seconds':self.code_lifetime_seconds,'completed_evidence':'encrypted-verifier-v1'}
        if self.preserve_expired_pending:result['preserve_expired_pending']=True
        return result

    def plan(self,row,configurations):
        if row.get('authorization_code') is None:
            if self.preserve_expired_pending:
                return {'retained':row,'native':_pending_native_row(row,configurations,self.authorization,allow_expired=True)}
            return super().plan(row,configurations)
        plan=completed_native_plan(row,configurations,self.authorization,self.recovery,code_lifetime_seconds=self.code_lifetime_seconds)
        # Durable JSON uses canonical base64, never plaintext verified claims.
        plan['journal']['content']=base64.b64encode(plan['journal']['content']).decode()
        return plan

    def validate_evidence(self,state):
        for plan in state['plans']:
            if not plan.get('journal'):continue
            payload=self.authorization.open(base64.urlsafe_b64decode(plan['native']['identity_data']+'='*(-len(plan['native']['identity_data'])%4)),plan['native']['auth_session'])
            claims,expiry=self.recovery.completed_claims(plan['retained'],payload['configuration'])
            if claims!=payload['claims'] or plan['journal']['expires_at']>expiry:
                raise ValueError('Completed verifier evidence changed')
