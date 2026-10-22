"""Private combined public keys for original-binary staff/credential recovery.

Issuer credential keys do not authorize staff roles: the Java authority adapter
separately binds those roles to the staff issuer's own key identifiers.
"""
import hashlib,json,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
import httpx

def combined_server(settings):
    sources=settings['sources']
    if len(sources)!=2 or len(set(sources))!=2:raise ValueError('Two pinned public key sources required')
    for value in sources:
        url=urlsplit(value)
        if (url.scheme!='http' or url.username or url.password or url.query or url.fragment
            or not (url.hostname=='127.0.0.1' or url.hostname.startswith('10.43.'))):
            raise ValueError('Pinned internal or recovery-loopback source required')
    lock=threading.Lock();cache={'expires':0,'body':None}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if self.path!='/jwks.json':self.send_error(404);return
            try:
                with lock:
                    if time.monotonic()>=cache['expires']:
                        keys={}
                        with httpx.Client(timeout=3,trust_env=False,follow_redirects=False) as client:
                            for source in sources:
                                with client.stream('GET',source) as response:
                                    response.raise_for_status();body=bytearray()
                                    for chunk in response.iter_bytes():
                                        body.extend(chunk)
                                        if len(body)>262144:raise ValueError('Public key response too large')
                                values=json.loads(body)['keys']
                                if not isinstance(values,list) or len(values)>64:raise ValueError('Bounded key list required')
                                for key in values:
                                    if (not isinstance(key,dict) or not isinstance(key.get('kid'),str)
                                        or key.get('kty') not in {'RSA','EC','OKP'}
                                        or set(key)&{'d','p','q','dp','dq','qi','oth','k'}):raise ValueError('Public keys only')
                                    if key['kid'] in keys and keys[key['kid']]!=key:raise ValueError('Ambiguous signing key identifier')
                                    keys[key['kid']]=key
                        cache.update(body=json.dumps({'keys':list(keys.values())}).encode(),expires=time.monotonic()+10)
                    body=cache['body']
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            except Exception:
                self.send_response(503);self.send_header('Content-Length','0');self.end_headers()
    address=settings.get('address','127.0.0.1')
    if address not in {'127.0.0.1','10.42.0.1'}:raise ValueError('Private recovery listener required')
    return ThreadingHTTPServer((address,settings['port']),Handler)

if __name__=='__main__':
    import os
    from pathlib import Path
    combined_server(json.loads(Path(os.environ['KDBT_RECOVERY_JWKS_SETTINGS']).read_text())).serve_forever()
