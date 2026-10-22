"""Document recovery under production SQL admission, with durable retry intent.

Objects cannot join a PostgreSQL transaction. Persist the before image and
intent before each mutation; keep both producers fenced after an interruption
until this operation is retried and verified. This coordinator never releases
fences or grants ownership.
"""
import hashlib,json,os
from pathlib import Path
from registry_object_reconciliation import recover_native_object


class RegistryDocumentRecovery:
    def __init__(self,coordinator,storage,directory):
        self.coordinator,self.storage=coordinator,storage
        self.directory=Path(directory)
        if not self.directory.is_absolute():raise ValueError('Absolute private recovery directory required')
        self.directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        if self.directory.stat().st_mode & 0o077:raise ValueError('Recovery directory must be private')

    def _save(self,path,value):
        temporary=path.with_suffix('.tmp')
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as output:
            json.dump(value,output,sort_keys=True);output.flush();os.fsync(output.fileno())
        os.replace(temporary,path)
        fd=os.open(self.directory,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)

    def recover(self,source,native,operation_id,items,**admission):
        if not isinstance(operation_id,str) or not operation_id or not isinstance(items,list) or not items:raise ValueError('Explicit document operation and baseline manifest required')
        request={'operation_id':operation_id,'destination_bucket':self.storage.bucket,'items':items}
        digest=hashlib.sha256(json.dumps(request,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        path=self.directory/(hashlib.sha256(operation_id.encode()).hexdigest()+'.json')
        with self.coordinator.admission(source,native,**admission) as assert_admitted:
            if path.exists():
                record=json.loads(path.read_text())
                if record['request_digest']!=digest:raise ValueError('Document recovery operation was reused with another manifest')
            else:record={'request_digest':digest,'request':request,'state':'INTENT','objects':{}};self._save(path,record)
            for item in items:
                if set(item)!={'bucket','store_id','baseline'}:raise ValueError('Complete explicit object baseline required')
                key=hashlib.sha256((item['bucket']+'\0'+item['store_id']).encode()).hexdigest()
                recovery_key='recovery/native-return/'+hashlib.sha256(operation_id.encode()).hexdigest()+'/'+key
                def persist(intent):
                    record['objects'][key]={'state':'INTENT',**intent};self._save(path,record)
                result=recover_native_object(self.storage,item['store_id'],item['bucket'],item['baseline'],recovery_key=recovery_key,assert_fenced=assert_admitted,persist_intent=persist)
                record['objects'][key]={**record['objects'].get(key,{}),'state':'COMPLETE',**result};self._save(path,record)
            record['state']='COMPLETE';self._save(path,record)
        return {'objects':len(items),'state':'COMPLETE','intent_digest':digest}
