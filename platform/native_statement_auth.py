"""Purpose-bound service authentication for bank statement callbacks."""
import hashlib,hmac,time
from fastapi import HTTPException


class NativeStatementAuthentication:
    def __init__(self,keys,*,clock=time.time,max_skew=300):
        if not keys or any(not isinstance(key,str) or not key or not isinstance(value,str) or len(value.encode())<32 for key,value in keys.items()):raise ValueError('Explicit callback keys of at least 32 bytes required')
        self.keys,self.clock,self.max_skew=dict(keys),clock,max_skew
    @staticmethod
    def message(timestamp,body):return ('kdbt-statement-v1\nPOST\n/upload_mt940\n'+str(timestamp)+'\n'+hashlib.sha256(body).hexdigest()).encode()
    def headers(self,key_id,body):
        timestamp=str(int(self.clock()));signature=hmac.new(self.keys[key_id].encode(),self.message(timestamp,body),hashlib.sha256).hexdigest()
        return {'X-KDBT-Callback-Key':key_id,'X-KDBT-Callback-Time':timestamp,'X-KDBT-Callback-Signature':signature}
    def __call__(self,request,body):
        try:
            key_id=request.headers.get('x-kdbt-callback-key','');timestamp=request.headers.get('x-kdbt-callback-time','');supplied=request.headers.get('x-kdbt-callback-signature','')
            if key_id not in self.keys or not timestamp.isdecimal() or len(timestamp)>12 or abs(self.clock()-int(timestamp))>self.max_skew or len(supplied)!=64:raise ValueError('Invalid callback authority')
            expected=hmac.new(self.keys[key_id].encode(),self.message(timestamp,body),hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected,supplied):raise ValueError('Invalid callback signature')
            return key_id
        except Exception:raise HTTPException(401,'Bank statement callback authentication failed') from None
