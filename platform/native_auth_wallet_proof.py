"""Pinned-database wallet proof validation shared by native identity services."""
import base64
import datetime
import hashlib
import hmac

import jwt
import psycopg2
from cryptography import x509
from cryptography.hazmat.primitives import hashes

class WalletProofFailure(ValueError):pass

def b64(value):return base64.urlsafe_b64encode(value).decode().rstrip('=')
def sha(value):return b64(hashlib.sha3_256(value.encode()).digest())


def verify_wallet_token(connection, individual, token, *, audience='esignet-binding'):
    try:
        if not isinstance(token, str) or len(token) > 32768:
            raise ValueError()
        header = jwt.get_unverified_header(token)
        thumbprint = header.get('x5t#S256')
        if header.get('alg') != 'RS256' or header.get('crit') or not isinstance(thumbprint, str):
            raise ValueError()
        with psycopg2.connect(**connection) as database, database.cursor() as cursor:
            cursor.execute('SET TRANSACTION READ ONLY')
            cursor.execute('''SELECT certificate FROM esignet.public_key_registry
                WHERE id_hash=%s AND auth_factor='WLA' AND thumbprint=%s AND expire_dtimes>NOW()''',
                           (sha(individual), thumbprint))
            certificates = [row[0] for row in cursor.fetchall()]
        if len(certificates) != 1:
            raise ValueError()
        cert = x509.load_pem_x509_certificate(certificates[0].encode())
        now = datetime.datetime.now(datetime.timezone.utc)
        if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
            raise ValueError()
        if not hmac.compare_digest(b64(cert.fingerprint(hashes.SHA256())), thumbprint):
            raise ValueError()
        claims = jwt.decode(token, cert.public_key(), algorithms=['RS256'], audience=audience,
                            subject=individual, options={'require': ['sub', 'aud', 'exp', 'iss', 'iat']})
        if not isinstance(claims['iss'], str) or not claims['iss'] or claims['exp'] - claims['iat'] > 600:
            raise ValueError()
        return claims
    except WalletProofFailure:
        raise
    except (ValueError, TypeError, KeyError, jwt.PyJWTError):
        raise WalletProofFailure('invalid_wla_token') from None
