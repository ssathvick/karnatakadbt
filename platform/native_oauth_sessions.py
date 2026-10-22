"""Framework-independent Redis OAuth state and refresh-session persistence.

Preserves installed IAM key/JSON formats. Compare-and-swap rotation prevents a
late refresh from resurrecting logout or overwriting a newer refresh token.
All records retain absolute expiry across restart and migration.
"""
import json
import secrets
from datetime import datetime, timedelta, timezone


class NativeOAuthSessions:
    def __init__(self, redis, *, transaction_ttl=300, refresh_ttl=1800, clock=None):
        if transaction_ttl <= 0 or refresh_ttl <= 0:
            raise ValueError('Positive session lifetimes required')
        self.redis = redis
        self.transaction_ttl, self.refresh_ttl = transaction_ttl, refresh_ttl
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _read(self, raw):
        if raw is None:
            return None
        try:
            value = json.loads(raw)
            expiry = datetime.fromisoformat(value['expires_at'].replace('Z', '+00:00'))
            if expiry.tzinfo is None or expiry <= self.clock():
                return None
            return value
        except (ValueError, TypeError, KeyError):
            return None

    def create_transaction(self, provider_id, redirect_uri, metadata=None, context=None):
        now = self.clock()
        value = dict(state=secrets.token_urlsafe(32), code_verifier=secrets.token_urlsafe(48),
                     nonce=secrets.token_urlsafe(32), login_provider_id=provider_id,
                     redirect_uri=redirect_uri, created_at=now.isoformat(),
                     expires_at=(now + timedelta(seconds=self.transaction_ttl)).isoformat(),
                     server_metadata=metadata, context=context)
        self.redis.set('auth_tx:' + value['state'], json.dumps(value), ex=self.transaction_ttl, nx=True)
        return value

    def consume_transaction(self, state):
        if not isinstance(state, str) or not state or len(state) > 1024:
            return None
        # One atomic command, including across multiple API replicas.
        raw = self.redis.eval("local v=redis.call('GET',KEYS[1]); if v then redis.call('DEL',KEYS[1]) end; return v", 1, 'auth_tx:' + state)
        return self._read(raw)

    def create_session(self, session_id, token_response, issuer):
        now = self.clock()
        ttl = int(token_response.get('refresh_expires_in', self.refresh_ttl))
        if ttl <= 0 or not session_id or not issuer or not token_response.get('refresh_token'):
            raise ValueError('Invalid refresh session')
        value = dict(session_id=session_id, refresh_token=token_response['refresh_token'], issuer=issuer,
                     created_at=now.isoformat(), expires_at=(now + timedelta(seconds=ttl)).isoformat())
        self.redis.set('refresh_token:' + session_id, json.dumps(value), ex=ttl)
        return value

    def read_session(self, session_id):
        if not isinstance(session_id, str) or not session_id or len(session_id) > 1024:
            return None
        value = self._read(self.redis.get('refresh_token:' + session_id))
        if value and value.get('session_id') == session_id and value.get('issuer') and value.get('refresh_token'):
            return value
        return None

    def rotate_session(self, previous, token_response):
        ttl = int(token_response.get('refresh_expires_in', self.refresh_ttl))
        if ttl <= 0:
            return False
        value = dict(previous, refresh_token=token_response.get('refresh_token') or previous['refresh_token'],
                     expires_at=(self.clock() + timedelta(seconds=ttl)).isoformat())
        script = '''local raw=redis.call('GET',KEYS[1]); if not raw then return 0 end
        local old=cjson.decode(raw)
        if old.refresh_token~=ARGV[1] or old.expires_at~=ARGV[2] or old.issuer~=ARGV[3] then return 0 end
        redis.call('SET',KEYS[1],ARGV[4],'EX',ARGV[5]); return 1'''
        return bool(self.redis.eval(script, 1, 'refresh_token:' + previous['session_id'],
                                    previous['refresh_token'], previous['expires_at'], previous['issuer'],
                                    json.dumps(value), ttl))

    def delete_session(self, session_id):
        if session_id:
            self.redis.delete('refresh_token:' + session_id)
