"""Data-only serialization for retained Certify DTOs during controlled recovery.

No application classes are loaded. Descriptor templates are captured from the
retained binary during offline compatibility acceptance. This module does not
activate a writer, change routes or write a production cache.
"""
import base64
import copy
import math
import struct

import javaobj
from javaobj.v1.beans import JavaObject, JavaString
from native_auth_cache import descriptor


def java(value):
    if value is None or isinstance(value, JavaObject):
        return value
    if isinstance(value, str):
        return JavaString(value)
    if isinstance(value, bool):
        obj = JavaObject()
        obj.classdesc = descriptor('java.lang.Boolean', -3665804199014368530, ['value'], ['Z'])
    elif isinstance(value, int):
        if not -(2**63) <= value < 2**63:
            raise ValueError('Integer outside retained wire range')
        large = not -(2**31) <= value < 2**31
        obj = JavaObject()
        obj.classdesc = descriptor('java.lang.Long' if large else 'java.lang.Integer',
                                   4290774380558885855 if large else 1360826667806852920,
                                   ['value'], ['J' if large else 'I'],
                                   parent=descriptor('java.lang.Number', -8742448824652078965))
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('Non-finite claim')
        obj = JavaObject()
        obj.classdesc = descriptor('java.lang.Double', -9172774392245257468, ['value'], ['D'],
                                   parent=descriptor('java.lang.Number', -8742448824652078965))
    elif isinstance(value, list):
        obj = JavaObject()
        obj.classdesc = descriptor('java.util.ArrayList', 8683452581122892189, ['size'], ['I'], 3)
        obj.size = len(value)
        obj.annotations = [struct.pack('>i', len(value)).decode('latin1')] + [java(item) for item in value]
        return obj
    elif isinstance(value, dict):
        obj = JavaObject()
        obj.classdesc = descriptor('java.util.HashMap', 362498820763181265, ['loadFactor', 'threshold'], ['F', 'I'], 3)
        obj.loadFactor, obj.threshold = .75, 12
        obj.annotations = [struct.pack('>ii', 16, len(value)).decode('latin1')]
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError('String claim keys required')
            obj.annotations.extend([JavaString(key), java(item)])
        return obj
    else:
        raise ValueError('Unsupported claim type')
    obj.value = value
    return obj


class CertifyRecoveryWire:
    def __init__(self, templates):
        self.templates = {name: javaobj.loads(base64.b64decode(value, validate=True)) for name, value in templates.items()}

    def dto(self, name, fields):
        result = copy.deepcopy(self.templates[name])
        desc = result.classdesc
        seen = set()
        while desc:
            for field, kind in zip(desc.fields_names, desc.fields_types):
                seen.add(field)
                value = fields.get(field)
                if str(kind) in ['J', 'I']:
                    value = value or 0
                elif str(kind) == 'Z':
                    value = bool(value)
                else:
                    value = java(value)
                setattr(result, field, value)
            desc = desc.superclass
        if set(fields) - seen:
            raise ValueError('Unknown retained DTO field')
        return result

    def transaction(self, payload, expires_at):
        issued = payload.get('nonce_issued_at')
        if not isinstance(issued, int) or not 0 < issued < expires_at or not payload.get('access_token_hash'):
            raise ValueError('Recovery metadata incomplete')
        return javaobj.dumps(self.dto('transaction', {
            'claims': payload['claims'], 'credentialConfigurationId': payload['configuration'],
            'createdAt': payload['created_at'], 'cNonce': payload['nonce'],
            'cNonceIssuedEpoch': issued, 'cNonceExpireSeconds': int(expires_at) - issued}))

    def code(self, payload, expires_at):
        return javaobj.dumps(self.dto('code', {'claims': payload['claims'],
            'credentialConfigurationId': payload['configuration'], 'txnCode': payload['tx_code'],
            'createdAt': payload['created_at'] * 1000, 'expiresAt': int(expires_at * 1000)}))

    def offer(self, payload, issuer):
        tx_code = self.dto('tx_code', {'length': payload['tx_length'], 'inputMode': payload['tx_mode'],
            'description': 'Please enter the transaction code provided to you'}) if payload['tx_length'] else None
        preauth = self.dto('preauth_grant', {'preAuthorizedCode': payload['code'], 'txCode': tx_code})
        grant = self.dto('grant', {'preAuthorizedCode': preauth})
        return javaobj.dumps(self.dto('offer', {'credentialIssuer': issuer,
            'credentialConfigurationIds': [payload['configuration']], 'grants': grant}))
