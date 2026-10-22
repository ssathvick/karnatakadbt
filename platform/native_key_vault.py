"""Native software-key vault candidate; not a hardware-security equivalence claim.

PKCS#11 non-exportable legacy keys are never read or converted here. A caller
must explicitly provision candidate keys or import PUBLIC verification material.
Production rotation and trust changes belong to the migration coordinator.
"""
import base64,datetime,json,os,secrets,sqlite3,time,uuid
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec,ed25519,padding,rsa,utils
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidSignature,InvalidTag

def encode(value):return base64.urlsafe_b64encode(value).decode().rstrip('=')
def decode(value):return base64.urlsafe_b64decode(value+'='*(-len(value)%4))
def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
class VaultFailure(Exception):pass
class NativeKeyVault:
 ALGORITHMS={'RS256','RS384','RS512','PS256','PS384','PS512','ES256','ES256K','ES384','ES512','EdDSA'}
 def __init__(self,path,master_key,*,clock=time.time):
  if len(master_key)!=32:raise ValueError('AES-256 wrapping key required')
  self.path,self.aead,self.clock=Path(path),AESGCM(master_key),clock;self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
  with self.connect() as c:c.executescript('''PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS vault_keys(id TEXT PRIMARY KEY,application TEXT NOT NULL,reference TEXT NOT NULL,algorithm TEXT NOT NULL,private_blob BLOB,public_pem BLOB NOT NULL,state TEXT NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS vault_aliases(application TEXT NOT NULL,reference TEXT NOT NULL,key_id TEXT NOT NULL,PRIMARY KEY(application,reference));
CREATE TABLE IF NOT EXISTS vault_audit(id INTEGER PRIMARY KEY,action TEXT NOT NULL,key_id TEXT,at REAL NOT NULL);''')
  self.path.chmod(0o600)
 def connect(self):
  c=sqlite3.connect(self.path,timeout=15);c.row_factory=sqlite3.Row;return c
 @staticmethod
 def scope(application,reference):
  if not isinstance(application,str) or not application or len(application)>128 or not isinstance(reference,str) or len(reference)>256:raise VaultFailure('Invalid key scope')
 @staticmethod
 def aad(row):return canonical({k:row[k] for k in ['id','application','reference','algorithm']})
 def _wrap(self,row,pem):
  nonce=secrets.token_bytes(12);return nonce+self.aead.encrypt(nonce,pem,self.aad(row))
 def _private(self,row):
  if row['state']!='ACTIVE' or row['private_blob'] is None:raise VaultFailure('Key is unavailable for private operations')
  value=row['private_blob']
  try:return serialization.load_pem_private_key(self.aead.decrypt(value[:12],value[12:],self.aad(row)),password=None)
  except (InvalidTag,ValueError):raise VaultFailure('Key recovery authentication failed')
 def generate(self,application,reference,algorithm='RS256',*,rotate=False):
  self.scope(application,reference)
  if algorithm not in self.ALGORITHMS:raise VaultFailure('Unsupported signing algorithm')
  if algorithm.startswith(('RS','PS')):private=rsa.generate_private_key(public_exponent=65537,key_size=3072)
  elif algorithm.startswith('ES'):private=ec.generate_private_key({'ES256':ec.SECP256R1(),'ES256K':ec.SECP256K1(),'ES384':ec.SECP384R1(),'ES512':ec.SECP521R1()}[algorithm])
  else:private=ed25519.Ed25519PrivateKey.generate()
  row={'id':uuid.uuid4().hex,'application':application,'reference':reference,'algorithm':algorithm};pem=private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption());public=private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
  with self.connect() as c:
   c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT key_id FROM vault_aliases WHERE application=? AND reference=?',(application,reference)).fetchone()
   if old and not rotate:raise VaultFailure('Active alias already exists; rotation must be explicit')
   c.execute('INSERT INTO vault_keys VALUES(?,?,?,?,?,?,?,?)',(row['id'],application,reference,algorithm,self._wrap(row,pem),public,'ACTIVE',self.clock()))
   if old:c.execute("UPDATE vault_keys SET state='VERIFY_ONLY' WHERE id=?",(old['key_id'],))
   c.execute('INSERT OR REPLACE INTO vault_aliases VALUES(?,?,?)',(application,reference,row['id']));c.execute('INSERT INTO vault_audit(action,key_id,at) VALUES(?,?,?)',('rotation' if old else 'generation',row['id'],self.clock()))
  return self.public(row['id'],application,reference)
 def row(self,kid,application,reference):
  self.scope(application,reference)
  with self.connect() as c:row=c.execute('SELECT * FROM vault_keys WHERE id=? AND application=? AND reference=?',(kid,application,reference)).fetchone()
  if not row:raise VaultFailure('Key is not registered in this scope')
  return dict(row)
 def active(self,application,reference):
  self.scope(application,reference)
  with self.connect() as c:row=c.execute('SELECT key_id FROM vault_aliases WHERE application=? AND reference=?',(application,reference)).fetchone()
  if not row:raise VaultFailure('No active signing key')
  return self.row(row['key_id'],application,reference)
 def public(self,kid,application,reference):
  row=self.row(kid,application,reference);return {'kid':row['id'],'application':application,'reference':reference,'algorithm':row['algorithm'],'state':row['state'],'public_key':row['public_pem'].decode()}
 def import_verification_key(self,kid,application,reference,algorithm,public_material):
  self.scope(application,reference)
  if algorithm not in self.ALGORITHMS or not isinstance(kid,str) or not kid or len(kid)>256:raise VaultFailure('Invalid public-key registration')
  raw=public_material.encode() if isinstance(public_material,str) else public_material
  try:
   public=x509.load_pem_x509_certificate(raw).public_key() if b'BEGIN CERTIFICATE' in raw else serialization.load_pem_public_key(raw)
  except ValueError:raise VaultFailure('Public key or certificate required; private keys are not accepted')
  self._key_type(public,algorithm);pem=public.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
  with self.connect() as c:
   c.execute('BEGIN IMMEDIATE')
   try:c.execute('INSERT INTO vault_keys VALUES(?,?,?,?,?,?,?,?)',(kid,application,reference,algorithm,None,pem,'VERIFY_ONLY',self.clock()))
   except sqlite3.IntegrityError:raise VaultFailure('Registered key IDs cannot be overwritten')
   c.execute('INSERT INTO vault_audit(action,key_id,at) VALUES(?,?,?)',('public-key-import',kid,self.clock()))
  return self.public(kid,application,reference)
 @staticmethod
 def _key_type(key,algorithm):
  if algorithm.startswith(('RS','PS')) and (not isinstance(key,(rsa.RSAPrivateKey,rsa.RSAPublicKey)) or key.key_size<2048):raise VaultFailure('RSA key and algorithm mismatch')
  if algorithm.startswith('ES'):
   if not isinstance(key,(ec.EllipticCurvePrivateKey,ec.EllipticCurvePublicKey)) or key.curve.name!={'ES256':'secp256r1','ES256K':'secp256k1','ES384':'secp384r1','ES512':'secp521r1'}[algorithm]:raise VaultFailure('EC key and algorithm mismatch')
  if algorithm=='EdDSA' and not isinstance(key,(ed25519.Ed25519PrivateKey,ed25519.Ed25519PublicKey)):raise VaultFailure('Ed25519 key required')
 @staticmethod
 def _hash(algorithm):return {'256':hashes.SHA256(),'384':hashes.SHA384(),'512':hashes.SHA512()}['256' if algorithm=='ES256K' else algorithm[-3:]]
 def sign_jws(self,application,reference,payload,*,detached=False):
  if not isinstance(payload,bytes) or len(payload)>1024*1024:raise VaultFailure('Bounded byte payload required')
  row=self.active(application,reference);key=self._private(row);algorithm=row['algorithm'];self._key_type(key,algorithm)
  header=encode(canonical({'alg':algorithm,'kid':row['id']}));body=encode(payload);signed=(header+'.'+body).encode()
  if algorithm.startswith('RS'):signature=key.sign(signed,padding.PKCS1v15(),self._hash(algorithm))
  elif algorithm.startswith('PS'):
   h=self._hash(algorithm);signature=key.sign(signed,padding.PSS(mgf=padding.MGF1(h),salt_length=h.digest_size),h)
  elif algorithm.startswith('ES'):
   der=key.sign(signed,ec.ECDSA(self._hash(algorithm)));r,s=utils.decode_dss_signature(der);size=(key.key_size+7)//8;signature=r.to_bytes(size,'big')+s.to_bytes(size,'big')
  else:signature=key.sign(signed)
  return header+'.'+('' if detached else body)+'.'+encode(signature)
 def verify_jws(self,application,reference,compact,*,detached_payload=None):
  try:
   if not isinstance(compact,str) or len(compact)>2*1024*1024:raise ValueError()
   head,body,sig=compact.split('.');header=json.loads(decode(head))
   if not isinstance(header,dict) or set(header)-{'alg','kid','typ'} or not isinstance(header.get('kid'),str):raise ValueError()
   row=self.row(header['kid'],application,reference);algorithm=row['algorithm']
   if row['state']=='REVOKED' or header.get('alg')!=algorithm:raise ValueError()
   if detached_payload is not None:
    if body or not isinstance(detached_payload,bytes):raise ValueError()
    body=encode(detached_payload)
   key=serialization.load_pem_public_key(row['public_pem']);self._key_type(key,algorithm);data=(head+'.'+body).encode();signature=decode(sig)
   if algorithm.startswith('RS'):key.verify(signature,data,padding.PKCS1v15(),self._hash(algorithm))
   elif algorithm.startswith('PS'):
    h=self._hash(algorithm);key.verify(signature,data,padding.PSS(mgf=padding.MGF1(h),salt_length=h.digest_size),h)
   elif algorithm.startswith('ES'):
    size=(key.key_size+7)//8
    if len(signature)!=size*2:raise ValueError()
    der=utils.encode_dss_signature(int.from_bytes(signature[:size],'big'),int.from_bytes(signature[size:],'big'));key.verify(der,data,ec.ECDSA(self._hash(algorithm)))
   else:key.verify(signature,data)
   return decode(body)
  except (ValueError,TypeError,KeyError,InvalidSignature,VaultFailure):raise VaultFailure('Signature is invalid or the key is outside the approved scope')
 def encrypt_jwe(self,application,reference,plaintext):
  if not isinstance(plaintext,bytes) or len(plaintext)>1024*1024:raise VaultFailure('Bounded byte payload required')
  row=self.active(application,reference);key=serialization.load_pem_public_key(row['public_pem'])
  if not isinstance(key,rsa.RSAPublicKey):raise VaultFailure('RSA key required for RSA-OAEP-256')
  protected=encode(canonical({'alg':'RSA-OAEP-256','enc':'A256GCM','kid':row['id']}));cek=secrets.token_bytes(32);iv=secrets.token_bytes(12)
  wrapped=key.encrypt(cek,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None));cipher=AESGCM(cek).encrypt(iv,plaintext,protected.encode())
  return '.'.join([protected,encode(wrapped),encode(iv),encode(cipher[:-16]),encode(cipher[-16:])])
 def decrypt_jwe(self,application,reference,compact):
  try:
   if not isinstance(compact,str) or len(compact)>2*1024*1024:raise ValueError()
   protected,wrapped,iv,body,tag=compact.split('.');header=json.loads(decode(protected))
   if set(header)!={'alg','enc','kid'} or header['alg']!='RSA-OAEP-256' or header['enc']!='A256GCM':raise ValueError()
   row=self.row(header['kid'],application,reference)
   # Rotation preserves old decryption capability; revocation disables it.
   if row['state'] not in {'ACTIVE','VERIFY_ONLY'} or row['private_blob'] is None:raise ValueError()
   key=self._private({**row,'state':'ACTIVE'})
   if not isinstance(key,rsa.RSAPrivateKey) or len(decode(iv))!=12 or len(decode(tag))!=16:raise ValueError()
   cek=key.decrypt(decode(wrapped),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
   return AESGCM(cek).decrypt(decode(iv),decode(body)+decode(tag),protected.encode())
  except (ValueError,TypeError,KeyError,InvalidTag,VaultFailure):raise VaultFailure('Ciphertext authentication or key-scope validation failed')
 def revoke(self,kid,application,reference):
  self.row(kid,application,reference)
  with self.connect() as c:
   c.execute('BEGIN IMMEDIATE');c.execute("UPDATE vault_keys SET state='REVOKED' WHERE id=?",(kid,));c.execute('DELETE FROM vault_aliases WHERE application=? AND reference=? AND key_id=?',(application,reference,kid));c.execute('INSERT INTO vault_audit(action,key_id,at) VALUES(?,?,?)',('revocation',kid,self.clock()))
