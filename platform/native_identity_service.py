"""Native identity simulator authority. No legacy HTTP calls or MOSIP imports.

Production citizen authentication remains disabled: this preserves the existing
synthetic identity test system, and is not an Aadhaar integration.
"""
import base64,datetime,json,os
from pathlib import Path
import jwt,psycopg2
from cryptography import x509
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from native_identity_sandbox import build
from native_identity_contract import contract

def create(settings):
 def client_authorizer(rp,client):
  with psycopg2.connect(**settings['client_registry_connection']) as c,c.cursor() as q:
   q.execute('SET TRANSACTION READ ONLY');q.execute('SELECT count(*) FROM esignet.client_detail WHERE id=%s AND rp_id=%s',(client,rp));return q.fetchone()[0]==1
 config={**settings,'client_authorizer':client_authorizer}
 if settings.get('wallet_registry_connection'):
  from native_auth_wallet_proof import verify_wallet_token
  def wallet_verifier(individual,token):
   try:
    verify_wallet_token(settings['wallet_registry_connection'],individual,token,audience=settings.get('wallet_audience','esignet-binding'));return True
   except Exception:return False
  config['wallet_token_verifier']=wallet_verifier

 def signer(payload):
  directory=Path(settings['signing_vault_directory']);raw=(directory/'vault.bin').read_bytes()
  entries=json.loads(AESGCM((directory/'master.key').read_bytes()).decrypt(raw[:12],raw[12:],b'native-java-keystore-v1:mock'));entry=entries[settings['signing_alias']]
  private=serialization.load_der_private_key(base64.b64decode(entry['private']),None)
  cert=x509.load_der_x509_certificate(base64.b64decode(entry['certificate']))
  kid=base64.urlsafe_b64encode(cert.fingerprint(hashes.SHA256())).decode().rstrip('=')
  return jwt.encode(payload,private,algorithm='RS256',headers={'kid':kid})
 app=build(config,signer)
 @app.get('/v1/mock-identity-system/actuator/health')
 def health():return {'status':'UP','native_identity_authority':True,'synthetic_only':True,'aadhaar_enabled':False}
 @app.get('/v1/mock-identity-system/v3/api-docs')
 def api_docs():return contract()
 return app

if os.environ.get('KDBT_NATIVE_IDENTITY_AUTHORITY_SETTINGS'):
 app=create(json.loads(Path(os.environ['KDBT_NATIVE_IDENTITY_AUTHORITY_SETTINGS']).read_text()))
