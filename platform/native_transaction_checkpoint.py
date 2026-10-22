"""Authenticated, restartable recovery of an explicitly bound group of stores.

The caller supplies real fence observations and exact store adapters. This
module cannot issue runtime admission, choose ownership or authorize routing.
Snapshots are taken after committed writes, not inferred from an empty baseline.
"""
import hashlib,json,os,re,secrets,stat,time
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BASE=Path('/opt/karnatakadbt/private/mosip-migration/remaining-three')
MAXIMUM=256*1024*1024

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()

def private(path,maximum=MAXIMUM+28):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o077 or info.st_size>maximum:
            raise ValueError('Protected bounded recovery artifact required')
        with os.fdopen(fd,'rb',closefd=False) as stream:return stream.read(maximum+1)
    finally:os.close(fd)

def atomic(path,data):
    path=Path(path);temporary=path.with_name(path.name+'.'+secrets.token_hex(12)+'.next')
    with temporary.open('xb') as stream:
        os.chmod(temporary,0o600);stream.write(data);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)

class TransactionCheckpoint:
    def __init__(self,folder,adapters,*,fenced,binding):
        self.folder=Path(folder).resolve(strict=True)
        if (not self.folder.is_relative_to(BASE) or self.folder.stat().st_uid!=0
                or self.folder.stat().st_mode&0o077):raise ValueError('Private checkpoint directory required')
        if not adapters or len(adapters)>64 or any(not re.fullmatch(r'[a-z0-9_-]{1,64}',k) for k in adapters):
            raise ValueError('Explicit bounded store inventory required')
        self.adapters,self.fenced,self.binding=dict(adapters),fenced,binding
        self.path=self.folder/'transaction-checkpoint.json';self.key_path=self.folder/'transaction-checkpoint.key'
        self.require()

    def require(self):
        if self.fenced() is not True:raise ValueError('All writers and workers must remain fenced')
        return True

    def aad(self,name):return canonical({'kind':'global-transaction-checkpoint-v1','store':name,'binding':self.binding})

    def seal(self,name,value,key):
        if not isinstance(value,bytes) or len(value)>MAXIMUM:raise ValueError('Bounded byte snapshot required')
        nonce=secrets.token_bytes(12);sealed=nonce+AESGCM(key).encrypt(nonce,value,self.aad(name))
        atomic(self.folder/(name+'.sealed'),sealed)
        return {'sha256':hashlib.sha256(sealed).hexdigest(),'plain_sha256':hashlib.sha256(value).hexdigest(),'bytes':len(value)}

    def load(self):
        self.require();key=private(self.key_path,32)
        if len(key)!=32:raise ValueError('Checkpoint key differs')
        sealed=private(self.path);manifest=json.loads(AESGCM(key).decrypt(sealed[:12],sealed[12:],self.aad('manifest')))
        if (manifest.get('version')!=1 or manifest.get('binding')!=self.binding
                or set(manifest.get('stores',{}))!=set(self.adapters)):
            raise ValueError('Checkpoint scope or binding differs')
        values={}
        # Authenticate and validate every payload before the first mutation.
        for name,adapter in sorted(self.adapters.items()):
            self.require();record=manifest['stores'][name]
            if adapter.identity()!=record['identity']:raise ValueError('Store identity differs: '+name)
            raw=private(self.folder/(name+'.sealed'))
            if hashlib.sha256(raw).hexdigest()!=record['sha256']:raise ValueError('Checkpoint ciphertext differs')
            value=AESGCM(key).decrypt(raw[:12],raw[12:],self.aad(name))
            if hashlib.sha256(value).hexdigest()!=record['plain_sha256']:raise ValueError('Checkpoint contents differ')
            adapter.validate(value);values[name]=value
        self.require();return manifest,values

    def capture(self):
        self.require()
        if self.path.exists() or self.key_path.exists():raise ValueError('Checkpoint already exists; recover it explicitly')
        key=secrets.token_bytes(32);atomic(self.key_path,key);records={}
        for name,adapter in sorted(self.adapters.items()):
            self.require();identity=adapter.identity();value=adapter.capture();adapter.validate(value)
            if adapter.identity()!=identity:raise ValueError('Store changed during capture')
            records[name]={**self.seal(name,value,key),'identity':identity,'summary':adapter.summary(value)}
        self.require()
        manifest={'version':1,'binding':self.binding,'created_at':time.time(),'stores':records}
        raw=canonical(manifest);nonce=secrets.token_bytes(12)
        atomic(self.path,nonce+AESGCM(key).encrypt(nonce,raw,self.aad('manifest')))
        self.load()
        atomic(self.folder/'recovery-progress.json',canonical({'phase':'CAPTURED','restored':[]}))
        return manifest

    def restore(self,*,stop_after=None):
        if stop_after is not None and stop_after not in self.adapters:raise ValueError('Unknown interruption checkpoint')
        manifest,values=self.load();restored=[]
        # Always reverify every adapter, including those whose previous commit
        # ACK was lost. Progress is diagnostic; it never authorizes skipping data.
        for name,adapter in sorted(self.adapters.items()):
            self.require()
            atomic(self.folder/'recovery-progress.json',canonical({'phase':'RESTORE_INTENT','store':name,'restored':restored}))
            adapter.restore(values[name]);self.require();adapter.verify(values[name]);restored.append(name)
            atomic(self.folder/'recovery-progress.json',canonical({'phase':'STORE_VERIFIED','store':name,'restored':restored}))
            if name==stop_after:return {'complete':False,'restored':restored}
        for name,adapter in sorted(self.adapters.items()):
            self.require();adapter.verify(values[name])
        atomic(self.folder/'recovery-progress.json',canonical({'phase':'COMPLETE','restored':restored}))
        return {'complete':True,'stores':len(restored),'summaries':{k:v['summary'] for k,v in manifest['stores'].items()},'writers_released':False}
