"""Current-file proof required before projecting a new private SQL identity."""
import hashlib
import os
import subprocess
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes


class RecoveredKeyProof:
    def __init__(self, engine, folder, *, java, compiler, helper):
        self.folder = Path(folder).resolve(strict=True)
        base = Path('/opt/karnatakadbt/private/mosip-migration/remaining-three')
        if not self.folder.is_relative_to(base) or self.folder.stat().st_uid != 0 or self.folder.stat().st_mode & 0o077:
            raise ValueError('Private root recovery directory required')
        self.inventory = {}
        with engine.vault.connect() as connection:
            for row in connection.execute('SELECT k.id,c.certificate FROM vault_keys k JOIN km_certificates c ON c.key_id=k.id WHERE k.private_blob IS NOT NULL'):
                self.inventory[row['id']] = x509.load_pem_x509_certificate(row['certificate'].encode()).fingerprint(hashes.SHA256()).hex()
        expected = self.folder/'expected-private-certificates.tsv'
        fd=os.open(expected,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as stream:
            stream.write(''.join(k+'\t'+v+'\n' for k,v in sorted(self.inventory.items())))
        classes=self.folder/'possession-proof-classes';classes.mkdir(mode=0o700)
        subprocess.run([str(compiler),'-d',str(classes),str(helper)],check=True,capture_output=True,timeout=30)
        archive=self.folder/'recovered.p12'
        self.archive_sha=hashlib.sha256(archive.read_bytes()).hexdigest()
        providers=list((Path(java).parents[2]/'inspection/original-libs').glob('bcprov-jdk18on-*.jar'))
        if len(providers)!=1:raise ValueError('Pinned retained crypto provider required')
        result=subprocess.run([str(java),'-cp',str(classes)+':'+str(providers[0]),'NativeRecoveredKeyProof',str(self.folder)],check=True,capture_output=True,timeout=30)
        if int(result.stdout)!=len(self.inventory) or hashlib.sha256(archive.read_bytes()).hexdigest()!=self.archive_sha:
            raise ValueError('Recovered private inventory changed')

    def require(self, kid, certificate):
        archive=self.folder/'recovered.p12'
        if archive.is_symlink() or hashlib.sha256(archive.read_bytes()).hexdigest()!=self.archive_sha:
            raise ValueError('Recovered private archive changed')
        expected=x509.load_pem_x509_certificate(certificate.encode()).fingerprint(hashes.SHA256()).hex()
        if self.inventory.get(kid)!=expected:
            raise ValueError('Recovered private certificate differs')
        return True
