"""Durable signed callback ingress while the existing service owns business writes."""
import asyncio,hashlib,hmac,json,os,sqlite3,time
from pathlib import Path
from contextlib import asynccontextmanager,contextmanager
import httpx
from cryptography.fernet import Fernet
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse

PATH='/consent/v1/awe/webhooks/decision'

class CallbackJournal:
    def __init__(self,settings):
        self.path=Path(settings['journal_path']);self.key=Fernet(Path(settings['encryption_key_path']).read_bytes())
        self.secret=settings['callback_secret'].encode();self.upstream=settings['upstream_url']
        if not self.secret or not self.upstream.startswith('http://'):raise ValueError('Explicit private callback configuration required')
        with self.connection() as c:
            c.execute('CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY,digest TEXT NOT NULL,body BLOB NOT NULL,state TEXT NOT NULL,created REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,last_attempt REAL)')
        self.path.chmod(0o600)
    @contextmanager
    def connection(self):
        c=sqlite3.connect(self.path,timeout=20);c.execute('PRAGMA synchronous=FULL')
        try:
            with c:yield c
        finally:c.close()
    def admit(self,event_id,raw):
        digest=hashlib.sha256(raw).hexdigest()
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            found=c.execute('SELECT digest,state FROM events WHERE event_id=?',(event_id,)).fetchone()
            if found:
                if found[0]!=digest:raise ValueError('Event identifier reused with different payload')
                return found[1]
            c.execute('INSERT INTO events(event_id,digest,body,state,created) VALUES(?,?,?,?,?)',(event_id,digest,self.key.encrypt(raw),'PENDING',time.time()))
        return 'PENDING'
    def pending(self):
        with self.connection() as c:return c.execute("SELECT event_id,body FROM events WHERE state='PENDING' ORDER BY created LIMIT 50").fetchall()
    def deliver(self,event_id):
        # A cross-process file lock covers the HTTP call. On a crash after the
        # upstream commit, replay is safe because the business owner dedupes.
        import fcntl
        with self.path.with_suffix('.lock').open('a') as lock:
            os.chmod(lock.name,0o600);fcntl.flock(lock,fcntl.LOCK_EX)
            with self.connection() as c:row=c.execute('SELECT body,state FROM events WHERE event_id=?',(event_id,)).fetchone()
            if row[1]=='DELIVERED':return True
            raw=self.key.decrypt(row[0]);stamp=str(int(time.time()))
            headers={'content-type':'application/json','x-approval-event-id':event_id,'x-approval-timestamp':stamp,'x-approval-signature':'sha256='+hmac.new(self.secret,stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()}
            try:
                with httpx.Client(trust_env=False,timeout=15,follow_redirects=False) as client:response=client.post(self.upstream,content=raw,headers=headers)
                delivered=200<=response.status_code<300
            except httpx.HTTPError:delivered=False
            with self.connection() as c:c.execute("UPDATE events SET state=?,attempts=attempts+1,last_attempt=? WHERE event_id=?",('DELIVERED' if delivered else 'PENDING',time.time(),event_id))
            return delivered

def build(settings):
    journal=CallbackJournal(settings)
    @asynccontextmanager
    async def lifespan(app):
        async def retry():
            while True:
                try:
                    for event_id,_ in await asyncio.to_thread(journal.pending):await asyncio.to_thread(journal.deliver,event_id)
                except Exception:pass # Durable pending work remains; no payload logging.
                await asyncio.sleep(10)
        task=asyncio.create_task(retry())
        yield
        task.cancel()
        try:await task
        except asyncio.CancelledError:pass
    app=FastAPI(title='KarnatakaDBT native signed callback gateway',lifespan=lifespan)
    @app.middleware('http')
    async def boundary(request,call_next):
        try:response=await call_next(request)
        except Exception:response=JSONResponse({'error':'Callback delivery unavailable; retry retained'},status_code=503)
        response.headers['cache-control']='no-store';response.headers['X-KarnatakaDBT-Callback']='native-durable-gateway';return response
    @app.get('/health')
    def health():return {'ready':True,'business_writer':settings.get('business_writer','existing-consent-service'),'pending_deliveries':len(journal.pending())}
    @app.post(settings.get('callback_path',PATH))
    async def callback(request:Request):
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>1024*1024:return JSONResponse({'error':'Callback too large'},status_code=413)
        raw=bytes(raw);stamp=request.headers.get('x-approval-timestamp','');signature=request.headers.get('x-approval-signature','')
        try:fresh=abs(time.time()-int(stamp))<=300
        except ValueError:fresh=False
        expected='sha256='+hmac.new(journal.secret,stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        if not fresh or not hmac.compare_digest(expected,signature):return JSONResponse({'error':'Invalid callback signature'},status_code=401)
        try:
            body=json.loads(raw);event_id=request.headers.get('x-approval-event-id','')
            if not isinstance(body,dict) or not event_id or len(event_id)>255 or (body.get('event_id') is not None and body['event_id']!=event_id):raise ValueError()
        except (ValueError,UnicodeDecodeError):return JSONResponse({'error':'Invalid callback event'},status_code=400)
        try:state=await asyncio.to_thread(journal.admit,event_id,raw)
        except ValueError:return JSONResponse({'error':'Event payload conflicts with committed delivery'},status_code=409)
        if state=='DELIVERED':return {'status':'duplicate'}
        if not await asyncio.to_thread(journal.deliver,event_id):return JSONResponse({'error':'Business owner unavailable; delivery retained'},status_code=503)
        return {'status':'delivered'}
    app.state.callback_journal=journal
    return app

if os.environ.get('KDBT_CALLBACK_SETTINGS'):app=build(json.loads(Path(os.environ['KDBT_CALLBACK_SETTINGS']).read_text()))
