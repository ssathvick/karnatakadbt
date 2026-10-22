"""Claim 169 label mapping and signed QR transport using generic CBOR/COSE/zlib.

The public labels preserve the retained wire vocabulary. No retained application
library is imported or executed by this implementation.
"""
import base64
import json
import zlib

import cbor2


LABELS = dict(zip(['ID', 'Version', 'Language', 'Full Name', 'First Name', 'Middle Name', 'Last Name',
    'Date of Birth', 'Gender', 'Address', 'Email ID', 'Phone Number', 'Nationality', 'Marital Status',
    'Guardian', 'Binary Image', 'Binary Image Format', 'Best Quality Fingers'], range(1, 19)))
LABELS.update(dict(zip(['Right Thumb', 'Right Pointer Finger', 'Right Middle Finger', 'Right Ring Finger',
    'Right Little Finger', 'Left Thumb', 'Left Pointer Finger', 'Left Middle Finger', 'Left Ring Finger',
    'Left Little Finger', 'Right Iris', 'Left Iris', 'Face', 'Right Palm Print', 'Left Palm Print', 'Voice'], range(50, 66))))
LABELS.update({'Data': 0, 'Data format': 1, 'Data sub format': 2, 'Data issuer': 3})
VALUES = {'Data format': {'Image': 0, 'Template': 1, 'Sound': 2, 'Bio Hash': 3},
    'Data sub format': {'PNG': 0, 'JPEG': 1, 'JPEG2000': 2, 'AVIF': 3, 'WEBP': 4, 'TIFF': 5, 'WSQ': 6,
        'Fingerprint Template ANSI 378': 0, 'Fingerprint Template ISO 19794-2': 1, 'Fingerprint Template NIST': 2, 'WAV': 0, 'MP3': 1},
    'Gender': {'Male': 1, 'Female': 2, 'Others': 3}, 'Marital Status': {'Unmarried': 1, 'Married': 2, 'Divorced': 3},
    'Binary Image Format': {'JPEG': 1, 'JPEG2': 2, 'AVIF': 3, 'WEBP': 4}}


def mapped(data):
    if not isinstance(data, dict):
        raise ValueError('QR entry must be an object')
    result = {}
    keys = {name.lower(): (name, value) for name, value in LABELS.items()}
    for name, value in data.items():
        if not isinstance(name, str):
            raise ValueError('Invalid QR label')
        canonical, label = keys.get(name.lower(), (name, name))
        if label in result:
            raise ValueError('Ambiguous QR label')
        if isinstance(value, dict):
            value = mapped(value)
        elif isinstance(value, list):
            value = [mapped(item) if isinstance(item, dict) else item for item in value]
        if canonical in VALUES and isinstance(value, str):
            value = {key.lower(): item for key, item in VALUES[canonical].items()}.get(value.lower(), value)
        result[label] = value
    return result


def base45(value):
    alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:'
    result = []
    for index in range(0, len(value), 2):
        pair = value[index:index + 2]
        number = int.from_bytes(pair, 'big')
        result.extend([alphabet[number % 45], alphabet[(number // 45) % 45]])
        if len(pair) == 2:
            result.append(alphabet[number // 2025])
    return ''.join(result)


def signed_entries(issuance, configuration, context):
    entries = configuration['qr_settings']
    if not isinstance(entries, list) or not 1 <= len(entries) <= 16 or issuance.templates is None:
        raise ValueError('Invalid QR settings')
    template = base64.b64encode(json.dumps(entries, ensure_ascii=False).encode()).decode()
    entries = issuance.templates.render(template, context, array=True)
    choices = {'RS256': ('CERTIFY_VC_SIGN_RSA', ''), 'ES256': ('CERTIFY_VC_SIGN_EC_R1', 'EC_SECP256R1_SIGN'),
               'ES256K': ('CERTIFY_VC_SIGN_EC_K1', 'EC_SECP256K1_SIGN'), 'EdDSA': ('CERTIFY_VC_SIGN_ED25519', 'ED25519_SIGN')}
    algorithm = configuration.get('qr_signature_algo') or configuration.get('signature_algo') or 'RS256'
    if configuration.get('qr_signature_algo'):
        application, reference = choices[algorithm]
    else:
        application, reference = configuration['key_manager_app_id'] or 'CERTIFY_VC_SIGN_RSA', configuration['key_manager_ref_id'] or ''
    result = []
    for entry in entries:
        payload = cbor2.dumps(mapped(entry)).hex()
        if len(payload) > 128 * 1024:
            raise ValueError('QR payload too large')
        signed = issuance.crypto.cose_sign({'applicationId': application, 'referenceId': reference,
            'algorithm': algorithm, 'issuer': issuance.configuration.settings['issuer'], 'claim169Payload': payload,
            'protectedHeader': {'kid': True, 'x5c': True}}, cwt=True)['signedData']
        result.append(base45(zlib.compress(signed.encode('utf-8'), 9)))
    return result
