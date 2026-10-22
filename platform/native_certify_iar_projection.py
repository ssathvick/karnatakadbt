"""Validated destination-only projection of native interactive session rows.

The caller owns the coordinated producer fence and SQL transaction. This
adapter never changes the encrypted native source or creates a fresh expiry.
Pending presentations require their verifier state to be recovered separately.
"""
import base64
import hashlib
import json
import datetime
import re


def timestamp(value):
    # PostgreSQL JSON can emit 1..6 fractional digits; Python 3.10 accepts
    # only millisecond/microsecond forms. Preserve precision before parsing.
    value=re.sub(r'\.(\d{1,6})(?=$|[+-]|Z)',lambda m:'.'+m[1].ljust(6,'0'),value)
    parsed=datetime.datetime.fromisoformat(value.replace('Z','+00:00'))
    return parsed.replace(tzinfo=datetime.timezone.utc).timestamp() if parsed.tzinfo is None else parsed.timestamp()


def retained_row(row, authorization, *, presentation_recovered=False):
    result = dict(row)
    identifier = row['auth_session']
    encoded = row['identity_data']
    if not isinstance(encoded, str) or len(encoded) > 2 * 1024 * 1024:
        raise ValueError('Invalid bounded interactive payload')
    payload = authorization.open(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)), identifier)
    raw = payload.get('auth_session')
    if not isinstance(raw, str) or hashlib.sha256(raw.encode()).hexdigest() != identifier:
        raise ValueError('Interactive session identity differs')
    if payload.get('client_id') != row['client_id'] or payload.get('code_challenge') != row['code_challenge']:
        raise ValueError('Interactive client or PKCE binding differs')
    if row['code_challenge_method'] != 'S256' or payload.get('nonce') != row['verify_nonce']:
        raise ValueError('Interactive nonce or PKCE method differs')
    completed = payload.get('completed') is True
    code = payload.get('code')
    if completed:
        if not isinstance(code, str) or hashlib.sha256(code.encode()).hexdigest() != row['authorization_code']:
            raise ValueError('Interactive code identity differs')
        if not isinstance(payload.get('claims'), dict):
            raise ValueError('Verified interactive claims missing')
        identity=payload['claims'].get('uin')
        if not isinstance(identity,str) or not 1<=len(identity)<=256:
            raise ValueError('Retained interactive identity mapping requires verified uin')
        result['authorization_code'] = code
        result['identity_data'] = identity
    else:
        if row['authorization_code'] is not None or row['is_code_used'] or code is not None:
            raise ValueError('Pending presentation has inconsistent code state')
        if presentation_recovered is not True:
            raise ValueError('Pending presentation verifier recovery required')
        result['identity_data'] = None
    result['auth_session'] = raw
    return result


def recovered_native_row(native_before, retained_after, authorization):
    """Recover a completed code's consumption without replacing native secrets.

    Pending presentations that complete in the retained engine need a separate
    verified-claims import; they cannot use this completed-code adapter.
    """
    expected = retained_row(native_before, authorization)
    if set(expected) != set(retained_after):
        raise ValueError('Interactive recovery schema differs')
    mutable = {'is_code_used', 'code_used_at'}
    if any(expected[key] != retained_after[key] for key in expected if key not in mutable):
        raise ValueError('Interactive recovery changed immutable state')
    before, after = native_before['is_code_used'], retained_after['is_code_used']
    if type(before) is not bool or type(after) is not bool or (before and not after):
        raise ValueError('Interactive consumption cannot be reversed')
    used_at = retained_after['code_used_at']
    if (after and used_at is None) or (not after and used_at is not None):
        raise ValueError('Interactive consumption timestamp differs')
    if before and native_before['code_used_at'] != used_at:
        raise ValueError('Consumed interactive timestamp cannot be replaced')
    return {**native_before, 'is_code_used': after, 'code_used_at': used_at}


def completed_pending_row(native_before, expected_retained, retained_after, authorization, *, verified_claims):
    """Reconcile completion only against the durable verifier's authenticated claims."""
    if not isinstance(verified_claims,dict) or not verified_claims:
        raise ValueError('Verified presentation claims required')
    allowed={'authorization_code','identity_data','is_code_used','code_issued_at','code_used_at'}
    if set(expected_retained)!=set(retained_after) or any(expected_retained[k]!=retained_after[k] for k in expected_retained if k not in allowed):
        raise ValueError('Pending recovery changed immutable binding')
    if retained_after['is_code_used'] is not True or retained_after['code_used_at'] is None or retained_after['code_issued_at'] is None:
        raise ValueError('Consumed retained code required')
    code=retained_after['authorization_code']
    if not isinstance(code,str) or not code.startswith('iar_auth_') or not 32<=len(code)<=128:
        raise ValueError('Retained code identity invalid')
    if not isinstance(verified_claims.get('uin'),str) or retained_after['identity_data']!=verified_claims['uin']:
        raise ValueError('Retained identity differs from verified presentation')
    identifier=native_before['auth_session'];encoded=native_before['identity_data']
    payload=authorization.open(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)),identifier)
    # Revalidate the encrypted pending identity before accepting any new fields.
    expected=retained_row(native_before,authorization,presentation_recovered=True)
    routing={'transaction_id','request_id','response_uri'}
    if any(expected[k]!=expected_retained[k] for k in expected if k not in routing) or payload.get('completed'):
        raise ValueError('Native pending recovery identity differs')
    payload.update(completed=True,claims=verified_claims,code=code)
    sealed=base64.urlsafe_b64encode(authorization.seal(payload,identifier)).decode().rstrip('=')
    return {**native_before,'authorization_code':hashlib.sha256(code.encode()).hexdigest(),'identity_data':sealed,
        'is_code_used':True,'code_issued_at':retained_after['code_issued_at'],'code_used_at':retained_after['code_used_at']},payload
