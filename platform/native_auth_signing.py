"""Standalone Python reader/writer for the existing native encrypted key format.

Only standard RSA/X.509/AES-GCM primitives are used. Compatibility metadata in
PostgreSQL selects the same live keys and preserves existing token trust.
"""
import base64,contextlib,datetime,fcntl,hashlib,json,os,secrets,tempfile,uuid
from pathlib import Path
import jwt,psycopg2
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509.oid import NameOID
from native_auth_cache import AuthenticationFailure,b64,canonical

class NativeSigningAuthority:
 def __init__(self,settings):
  self.settings=settings;self.path=Path(settings['directory']);self.aad=('native-java-keystore-v1:'+settings['scope']).encode()
  self.aead=AESGCM((self.path/'master.key').read_bytes())
 def read(self):
  raw=(self.path/'vault.bin').read_bytes()
  try:return json.loads(self.aead.decrypt(raw[:12],raw[12:],self.aad))
  except Exception:raise AuthenticationFailure('key_recovery_failed') from None
 @contextlib.contextmanager
 def locked(self):
  with (self.path/'vault.lock').open('a') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX);values=self.read();yield values
 def write(self,values):
  stat=(self.path/'vault.bin').stat();nonce=secrets.token_bytes(12);raw=nonce+self.aead.encrypt(nonce,canonical(values),self.aad)
  descriptor,name=tempfile.mkstemp(prefix='native-auth-key-',dir=self.path)
  try:
   os.fchmod(descriptor,0o600);os.fchown(descriptor,stat.st_uid,stat.st_gid)
   with os.fdopen(descriptor,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
   os.replace(name,self.path/'vault.bin')
   directory=os.open(self.path,os.O_RDONLY|os.O_DIRECTORY)
   try:os.fsync(directory)
   finally:os.close(directory)
  finally:
   if Path(name).exists():Path(name).unlink()
 def connect(self):return psycopg2.connect(**self.settings['connection'])
 def alias(self,app,ref=''):
  if app not in self.settings['applications'] or not isinstance(ref,str) or len(ref)>128:raise AuthenticationFailure('invalid_application_id')
  with self.connect() as c,c.cursor() as q:
   q.execute("SELECT row_to_json(t) FROM esignet.key_alias t WHERE app_id=%s AND ref_id=%s AND is_deleted=false AND key_gen_dtimes<=NOW() AND key_expire_dtimes>NOW()",(app,ref));rows=q.fetchall()
  if len(rows)!=1:raise AuthenticationFailure('key_unavailable')
  return rows[0][0]
 def key(self,app,ref=''):
  alias=self.alias(app,ref);entry=self.read().get(alias['id'])
  if not entry or not entry.get('private'):raise AuthenticationFailure('key_unavailable')
  cert=x509.load_der_x509_certificate(base64.b64decode(entry['certificate']));now=datetime.datetime.now(datetime.timezone.utc)
  if not cert.not_valid_before_utc<=now<cert.not_valid_after_utc:raise AuthenticationFailure('key_expired')
  return alias,serialization.load_der_private_key(base64.b64decode(entry['private']),None),cert
 def certificate(self,app,ref=''):
  alias=self.alias(app,ref);entry=self.read().get(alias['id'])
  if not entry:raise AuthenticationFailure('key_unavailable')
  cert=x509.load_der_x509_certificate(base64.b64decode(entry['certificate']))
  return {'certificate':cert.public_bytes(serialization.Encoding.PEM).decode(),'certSignRequest':None,
   'issuedAt':cert.not_valid_before_utc.isoformat().replace('+00:00','Z'),'expiryAt':cert.not_valid_after_utc.isoformat().replace('+00:00','Z'),'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00','Z')}
 def kid(self,alias,cert):
  configured=self.settings.get('jose_ids',{}).get(alias['id'])
  if configured:return configured
  return b64(hashlib.sha256(bytes.fromhex(alias['uni_ident'])).digest()) if alias.get('uni_ident') else b64(cert.fingerprint(hashes.SHA256()))
 def sign(self,claims,app='OIDC_SERVICE',ref='',headers=None):
  alias,key,cert=self.key(app,ref);return jwt.encode(claims,key,algorithm='RS256',headers={'kid':self.kid(alias,cert),**(headers or {})})
 def jwks(self):
  keys=[];values=self.read();now=datetime.datetime.now(datetime.timezone.utc)
  with self.connect() as c,c.cursor() as q:
   q.execute("SELECT row_to_json(t) FROM esignet.key_alias t WHERE app_id='OIDC_SERVICE' AND ref_id='' AND is_deleted=false AND key_expire_dtimes>NOW()")
   rows=[v[0] for v in q]
  for row in rows:
   entry=values.get(row['id'])
   if not entry or not entry.get('certificate'):continue
   cert=x509.load_der_x509_certificate(base64.b64decode(entry['certificate']));key=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cert.public_key()))
   key.update(kid=self.kid(row,cert),use='sig',alg='RS256');keys.append(key)
  return {'keys':keys}
 def verify(self,token,*,audience=None,issuer=None,required=None):
  try:
   header=jwt.get_unverified_header(token)
   if header.get('alg')!='RS256' or header.get('crit'):raise ValueError()
   matches=[v for v in self.jwks()['keys'] if v['kid']==header.get('kid')]
   if len(matches)!=1:raise ValueError()
   return jwt.decode(token,jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(matches[0])),algorithms=['RS256'],issuer=issuer,audience=audience,
    options={'verify_aud':audience is not None,'require':required or ['sub','iss','exp','iat']})
  except Exception:raise AuthenticationFailure('invalid_token') from None
 def upload(self,value):
  app=value.get('applicationId');ref=value.get('referenceId') or '';alias,key,old=self.key(app,ref)
  try:
   cert=x509.load_pem_x509_certificate(value['certificateData'].encode());now=datetime.datetime.now(datetime.timezone.utc)
   if cert.public_key().public_numbers()!=key.public_key().public_numbers() or not cert.not_valid_before_utc<=now<cert.not_valid_after_utc:raise ValueError()
   issuer=self.key('ROOT')[2] if app!='ROOT' else cert;cert.verify_directly_issued_by(issuer)
  except Exception:raise AuthenticationFailure('invalid_certificate') from None
  with self.locked() as values:
   values[alias['id']]['certificate']=base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode();self.write(values)
  return {'status':'SUCCESS','timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00','Z')}

 def ensure_wallet_issuer(self):
  """Create only the dedicated wallet issuer, retaining the existing root."""
  app='MOCK_BINDING_SERVICE'
  if app not in self.settings['applications']:raise AuthenticationFailure('invalid_application_id')
  with self.connect() as connection,connection.cursor() as cursor:
   cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('native-wallet-issuer',))
   cursor.execute("SELECT id FROM esignet.key_alias WHERE app_id=%s AND ref_id='' AND is_deleted=false AND key_expire_dtimes>NOW()",(app,))
   existing=cursor.fetchall()
   if existing:
    if len(existing)!=1:raise AuthenticationFailure('ambiguous_key')
    return
   root_alias,root_key,root_cert=self.key('ROOT')
   now=datetime.datetime.now(datetime.timezone.utc);expires=min(now+datetime.timedelta(days=1095),root_cert.not_valid_after_utc)
   private=rsa.generate_private_key(public_exponent=65537,key_size=3072)
   certificate=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'KarnatakaDBT Wallet Binding')]))
    .issuer_name(root_cert.subject).public_key(private.public_key()).serial_number(x509.random_serial_number())
    .not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(expires)
    .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
    .add_extension(x509.KeyUsage(digital_signature=True,content_commitment=False,key_encipherment=False,data_encipherment=False,key_agreement=False,key_cert_sign=True,crl_sign=True,encipher_only=False,decipher_only=False),critical=True)
    .sign(root_key,hashes.SHA256()))
   identifier=str(uuid.uuid4());entry={'private':base64.b64encode(private.private_bytes(serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())).decode(),'certificate':base64.b64encode(certificate.public_bytes(serialization.Encoding.DER)).decode()}
   # Persist encrypted material first. A database failure leaves an unreachable
   # encrypted entry, never metadata pointing to a missing private key.
   with self.locked() as values:
    values[identifier]=entry;self.write(values)
   cursor.execute('''INSERT INTO esignet.key_policy_def(app_id,key_validity_duration,is_active,pre_expire_days,access_allowed,cr_by,cr_dtimes,is_deleted)
    VALUES(%s,1095,true,30,'NA','native-migration',NOW(),false) ON CONFLICT(app_id) DO NOTHING''',(app,))
   cursor.execute('''INSERT INTO esignet.key_alias(id,app_id,ref_id,key_gen_dtimes,key_expire_dtimes,status_code,lang_code,cr_by,cr_dtimes,is_deleted,cert_thumbprint,uni_ident)
    VALUES(%s,%s,'',%s,%s,'ACTIVE','eng','native-migration',NOW(),false,%s,%s)''',
    (identifier,app,now.replace(tzinfo=None),expires.replace(tzinfo=None),certificate.fingerprint(hashes.SHA256()).hex().upper(),b64(hashlib.sha256((app+identifier).encode()).digest())))
