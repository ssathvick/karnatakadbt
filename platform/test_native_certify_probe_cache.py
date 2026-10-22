import base64,datetime,json,unittest
from unittest.mock import patch
import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding,BestAvailableEncryption,pkcs12
from cryptography.x509.oid import NameOID
from native_certify_probe_cache import probe_cache_equivalent


class ProbeCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'isolated-probe-test')])
        now=datetime.datetime.now(datetime.timezone.utc)
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
              .serial_number(1).not_valid_before(now-datetime.timedelta(minutes=1))
              .not_valid_after(now+datetime.timedelta(days=1)).sign(key,hashes.SHA256()))
        cls.archive=pkcs12.serialize_key_and_certificates(b'test',key,cert,None,BestAvailableEncryption(b'isolated'))
        cls.public=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        cls.public.pop('key_ops',None)
        cls.public['x5c']=[base64.b64encode(cert.public_bytes(Encoding.DER)).decode()]

    def verify(self,expected=None,actual=None,public=None):
        with patch('native_certify_probe_cache.javaobj.loads',return_value={'keys':[public or self.public]}):
            return probe_cache_equivalent(expected or {'jwks':{},'business':{}},
                actual or {'jwks':{'oauth-jwks':b'fixture'},'business':{}},self.archive,b'isolated')

    def test_public_metadata_regeneration(self):self.assertTrue(self.verify())
    def test_existing_metadata_must_match(self):
        self.assertFalse(self.verify(expected={'jwks':{'old':b'value'},'business':{}}))
    def test_business_change_rejected(self):
        self.assertFalse(self.verify(actual={'jwks':{'oauth-jwks':b'fixture'},'business':{'new':b'value'}}))
    def test_private_key_rejected(self):self.assertFalse(self.verify(public={**self.public,'d':'private'}))
    def test_changed_key_rejected(self):self.assertFalse(self.verify(public={**self.public,'n':'AQAB'}))
    def test_unknown_cache_entry_rejected(self):
        self.assertFalse(self.verify(actual={'jwks':{'unexpected':b'fixture'},'business':{}}))


if __name__=='__main__':unittest.main()
