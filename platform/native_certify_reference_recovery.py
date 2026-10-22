"""Original-library proof of wrapped reference keys, bound to one archive."""
import base64,hashlib,json,subprocess
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from native_certify_recovered_key_proof import RecoveredKeyProof

class ReferenceRecoveredKeyProof(RecoveredKeyProof):
    def __init__(self,engine,folder,*,java,compiler,helper,reference_helper):
        super().__init__(engine,folder,java=java,compiler=compiler,helper=helper)
        source=Path(java).parents[2]
        properties=json.loads((source/'effective-file-properties.json').read_text())
        splitter=properties['mosip.kernel.data-key-splitter']
        if not isinstance(splitter,str) or not 1<=len(splitter)<=64 or not splitter.isascii():
            raise ValueError('Pinned retained envelope delimiter required')
        with engine.vault.connect() as connection:
            original={row[0] for row in connection.execute("SELECT identifier FROM km_records WHERE kind='source-alias'")}
            references=[]
            for row in connection.execute("SELECT id,application,reference FROM vault_keys WHERE private_blob IS NOT NULL AND reference<>''"):
                if row['id'] in original:continue
                master=connection.execute("SELECT key_id FROM vault_aliases WHERE application=? AND reference=''",(row['application'],)).fetchone()
                if master is None:raise ValueError('Reference requires a recovered application master')
                references.append({'id':row['id'],'master':master[0]})
        request={'splitter':splitter,'tag_length':int(properties['mosip.kernel.crypto.gcm-tag-length']),
            'symmetric_algorithm':properties['mosip.kernel.crypto.symmetric-algorithm-name'],
            'asymmetric_algorithm':properties['mosip.kernel.crypto.asymmetric-algorithm-name'],
            'keystore_type':properties.get('mosip.kernel.keymanager.hsm.keystore-type','PKCS12'),
            'references':references}
        if request['tag_length']!=128 or request['symmetric_algorithm']!='AES/GCM/NoPadding':
            raise ValueError('Authenticated retained private-key envelope required')
        path=self.folder/'reference-wrap-request.json';path.write_text(json.dumps(request));path.chmod(0o600)
        classes=self.folder/'reference-wrap-classes';classes.mkdir(mode=0o700)
        classpath=str(source/'inspection/original-libs')+'/*'
        subprocess.run([str(compiler),'-proc:none','-cp',classpath,'-d',str(classes),str(reference_helper)],check=True,capture_output=True,timeout=30)
        result=subprocess.run([str(java),'-cp',str(classes)+':'+classpath,'NativeReferenceKeyRecovery',str(self.folder)],capture_output=True,timeout=60)
        if result.returncode:
            diagnostic=self.folder/'reference-wrapper-diagnostic.log';diagnostic.write_bytes(result.stdout+result.stderr);diagnostic.chmod(0o600)
            raise ValueError('Original reference-key wrapper proof failed; protected diagnostic retained')
        self.wrapper_path=self.folder/'reference-wrapped-keys.json'
        self.wrapper_sha=hashlib.sha256(self.wrapper_path.read_bytes()).digest()
        rows=json.loads(self.wrapper_path.read_text());self.wrappers={row['id']:row for row in rows}
        expected={row['id']:row['master'] for row in references}
        if len(rows)!=len(expected) or set(self.wrappers)!=set(expected):raise ValueError('Reference wrapper inventory differs')
        for identifier,row in self.wrappers.items():
            if row['master']!=expected[identifier] or row['certificate_sha256']!=self.inventory[identifier]:
                raise ValueError('Reference wrapper scope or certificate differs')
            raw=base64.urlsafe_b64decode(row['private_key']+'='*(-len(row['private_key'])%4))
            if not 256<len(raw)<=1024*1024:raise ValueError('Bounded encrypted reference-key envelope required')

    def reference_wrapper(self,kid,certificate):
        self.require(kid,certificate)
        if self.wrapper_path.is_symlink() or hashlib.sha256(self.wrapper_path.read_bytes()).digest()!=self.wrapper_sha:
            raise ValueError('Authenticated wrapped private material changed')
        row=self.wrappers.get(kid)
        if row is None:raise ValueError('Reference wrapper proof missing')
        if row['certificate_sha256']!=x509.load_pem_x509_certificate(certificate.encode()).fingerprint(hashes.SHA256()).hex():
            raise ValueError('Reference wrapper certificate differs')
        return dict(row)
