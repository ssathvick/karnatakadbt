"""Worker admission held across commits and protected from owner CAS races."""
import hashlib,json,sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT=Path('/opt/karnatakadbt/private/mosip-migration/remaining-three')

class CertifyWorkerGuard:
 def __init__(self,settings_path,settings,*,test_fence=None):
  self.path=Path(settings_path).resolve(strict=True);self.settings=settings
  if not self.path.is_relative_to(ROOT) or self.path.stat().st_uid!=0 or self.path.stat().st_mode&0o077:raise ValueError('Private worker configuration required')
  if settings.get('environment') not in {'CANDIDATE','NATIVE'} or 'rehearsal_receipt' in settings:raise ValueError('Private HTTP admission cannot authorize a worker')
  self.vault=Path(settings['crypto']['database']).resolve(strict=True)
  if not self.vault.is_relative_to(ROOT) or self.vault.stat().st_uid!=0 or self.vault.stat().st_mode&0o077:raise ValueError('Private authority store required')
  self.fence=ROOT/'production-cutover/producer-fence.json'
  if test_fence is not None:
   if settings['environment']!='CANDIDATE' or not self.path.parent.name.startswith('worker-guard-test-') or self.vault.parent!=self.path.parent:raise ValueError('Isolated candidate test fence only')
   self.fence=Path(test_fence)
  self.fingerprint=hashlib.sha256(self.path.read_bytes()).digest()
  self.receipt=None
  if settings['environment']=='NATIVE':
   from native_certify_activation import admit
   admit(settings,self.path.parent/'release')
   self.receipt=Path(settings['activation_receipt']).resolve(strict=True)
   if self.receipt.parent!=ROOT/'production-cutover' or self.receipt.stat().st_uid!=0 or self.receipt.stat().st_mode&0o077:raise ValueError('Protected LIVE worker receipt required')
   self.receipt_sha=hashlib.sha256(self.receipt.read_bytes()).digest()
  self.connection=None
  self.require()
 def require(self):
  if self.fence.exists() or self.fence.is_symlink():raise ValueError('Production producers are fenced')
  if hashlib.sha256(self.path.read_bytes()).digest()!=self.fingerprint:raise ValueError('Worker settings changed')
  if self.receipt and hashlib.sha256(self.receipt.read_bytes()).digest()!=self.receipt_sha:raise ValueError('Worker admission changed')
  if self.receipt:
   from native_certify_activation import admit
   admit(self.settings,self.path.parent/'release')
  if self.connection and self.connection.execute('SELECT owner FROM km_authority WHERE id=1').fetchone()!=(self.settings['environment'],):raise ValueError('Worker authority changed')
  return True
 @contextmanager
 def hold(self):
  self.require()
  connection=sqlite3.connect(self.vault,timeout=5)
  try:
   connection.execute('BEGIN IMMEDIATE');self.connection=connection;self.require()
   yield self.require
   self.require();connection.commit()
  except BaseException:
   connection.rollback();raise
  finally:self.connection=None;connection.close()
