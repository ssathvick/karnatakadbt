"""Native private WebSub hub with durable verification and signed delivery.

Publisher push uses the registry's register/publish/deregister extension.
Subscriptions implement challenge verification and expiring leases. Callback
capabilities are scoped to an explicitly enrolled topic and exact callback URL.
"""
import contextlib,datetime,hashlib,hmac,json,secrets,threading,uuid
from urllib.parse import parse_qs,urlsplit,urlunsplit,urlencode
from cryptography.fernet import Fernet
import httpx
from fastapi import FastAPI,HTTPException,Request,Response
from sqlalchemy import MetaData,Table,Column,String,Text,Boolean,Integer,DateTime,LargeBinary,Index,select,insert,update,and_,text

metadata=MetaData()
topics=Table('websub_topics',metadata,Column('name',Text,primary_key=True),Column('active',Boolean,nullable=False))
subscriptions=Table('websub_subscriptions',metadata,Column('id',String,primary_key=True),Column('topic',Text,nullable=False),Column('callback',Text,nullable=False),Column('active',Boolean,nullable=False),Column('revision',Integer,nullable=False),Column('lease_until',DateTime(timezone=True)),Column('secret',Text))
verifications=Table('websub_verifications',metadata,Column('id',String,primary_key=True),Column('subscription_id',String,nullable=False),Column('revision',Integer,nullable=False),Column('mode',String,nullable=False),Column('challenge',String,nullable=False),Column('lease_seconds',Integer,nullable=False),Column('secret',Text),Column('status',String,nullable=False),Column('attempts',Integer,nullable=False),Column('due',DateTime(timezone=True),nullable=False),Column('error',String))
messages=Table('websub_messages',metadata,Column('id',String,primary_key=True),Column('topic',Text,nullable=False),Column('body',LargeBinary,nullable=False),Column('content_type',String,nullable=False),Column('digest',String,nullable=False),Column('idempotency_key',String),Column('at',DateTime(timezone=True),nullable=False))
deliveries=Table('websub_deliveries',metadata,Column('id',String,primary_key=True),Column('message_id',String,nullable=False),Column('subscription_id',String,nullable=False),Column('status',String,nullable=False),Column('attempts',Integer,nullable=False),Column('due',DateTime(timezone=True),nullable=False),Column('error',String))
Index('ux_websub_message_replay',messages.c.topic,messages.c.idempotency_key,unique=True,postgresql_where=messages.c.idempotency_key.is_not(None))
for table in [verifications,deliveries]:Index('ix_'+table.name+'_pending',table.c.status,table.c.due)

def now():return datetime.datetime.now(datetime.timezone.utc)
def uid():return str(uuid.uuid4())
def valid_topic(value):return isinstance(value,str) and 0<len(value)<=2048 and not any(ord(ch)<32 or ch in '<>"' for ch in value)
def valid_callback(value):
    p=urlsplit(value)
    return p.scheme in {'http','https'} and bool(p.hostname) and not p.username and not p.password and not p.fragment and len(value)<=4096 and not any(ord(ch)<32 for ch in value)

class HubStore:
    def __init__(self,engine,encryption_key,hub_url,clock=now,transport=None,max_attempts=5,backoff_seconds=5,timeout=5):
        if not valid_callback(hub_url) or urlsplit(hub_url).query:raise ValueError('Explicit hub origin required')
        if not 1<=max_attempts<=20 or not 0<=backoff_seconds<=3600 or not 0<timeout<=30:raise ValueError('Invalid hub retry configuration')
        self.engine,self.cipher,self.hub_url=engine,Fernet(encryption_key),hub_url.rstrip('/')
        self.clock,self.transport=clock,transport
        self.max_attempts,self.backoff,self.timeout=max_attempts,backoff_seconds,timeout
    def initialize(self):metadata.create_all(self.engine)
    def lock(self,c,key):c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':'native-websub:'+key})
    def register(self,topic,active=True):
        with self.engine.begin() as c:
            self.lock(c,'topic:'+topic)
            exists=c.execute(select(topics.c.name).where(topics.c.name==topic)).first()
            if exists:c.execute(update(topics).where(topics.c.name==topic).values(active=active))
            else:c.execute(insert(topics).values(name=topic,active=active))
    def require_topic(self,c,topic):
        if c.execute(select(topics.c.active).where(topics.c.name==topic)).scalar_one_or_none() is not True:raise HTTPException(404,'Topic is not registered')
    def subscribe(self,topic,callback,mode,lease_seconds,secret):
        identity=hashlib.sha256(json.dumps([topic,callback],separators=(',',':')).encode()).hexdigest()
        with self.engine.begin() as c:
            self.lock(c,'subscription:'+identity);self.require_topic(c,topic)
            row=c.execute(select(subscriptions).where(subscriptions.c.id==identity)).mappings().first()
            revision=(row['revision'] if row else 0)+1
            if row:c.execute(update(subscriptions).where(subscriptions.c.id==identity).values(revision=revision))
            else:c.execute(insert(subscriptions).values(id=identity,topic=topic,callback=callback,active=False,revision=revision))
            c.execute(update(verifications).where(verifications.c.subscription_id==identity,verifications.c.status=='pending').values(status='superseded'))
            c.execute(insert(verifications).values(id=uid(),subscription_id=identity,revision=revision,mode=mode,challenge=secrets.token_urlsafe(32),lease_seconds=lease_seconds,
                secret=self.cipher.encrypt(secret.encode()).decode() if secret else None,status='pending',attempts=0,due=self.clock()))
    def publish(self,topic,body,content_type,key=None):
        if len(body)>32*1024*1024:raise HTTPException(413,'Content is too large')
        if key is not None and (not key or len(key)>255):raise HTTPException(400,'Invalid idempotency key')
        digest=hashlib.sha256(content_type.encode()+b'\0'+body).hexdigest()
        with self.engine.begin() as c:
            self.lock(c,'topic:'+topic);self.require_topic(c,topic)
            if key:
                previous=c.execute(select(messages.c.id,messages.c.digest).where(messages.c.topic==topic,messages.c.idempotency_key==key)).first()
                if previous:
                    if previous.digest!=digest:raise HTTPException(409,'Idempotency key refers to different content')
                    return {'message_id':previous.id,'replayed':True}
            identity=uid();stamp=self.clock()
            c.execute(insert(messages).values(id=identity,topic=topic,body=body,content_type=content_type,digest=digest,idempotency_key=key,at=stamp))
            subscribers=c.execute(select(subscriptions.c.id).where(subscriptions.c.topic==topic,subscriptions.c.active.is_(True),subscriptions.c.lease_until>stamp)).scalars()
            for subscriber in subscribers:c.execute(insert(deliveries).values(id=uid(),message_id=identity,subscription_id=subscriber,status='pending',attempts=0,due=stamp))
            return {'message_id':identity,'replayed':False}
    def retry(self,row,code):
        attempts=row['attempts']+1
        return {'attempts':attempts,'status':'exhausted' if attempts>=self.max_attempts else 'pending','due':self.clock()+datetime.timedelta(seconds=min(3600,self.backoff*2**(attempts-1))),'error':code}
    def tick(self,limit=4):
        if not 1<=limit<=100:raise ValueError('Bounded dispatch required')
        verified=sent=0
        for table in [verifications,deliveries]:
            with self.engine.connect() as candidate_connection:
                candidates=candidate_connection.execute(select(table.c.id,table.c.subscription_id).where(table.c.status=='pending',table.c.due<=self.clock()).order_by(table.c.due,table.c.id).limit(limit)).all()
            for candidate_id,subscription_id in candidates:
                with self.engine.begin() as c:
                    self.lock(c,'subscription:'+subscription_id)
                    row=c.execute(select(table).where(table.c.id==candidate_id,table.c.status=='pending',table.c.due<=self.clock()).with_for_update(skip_locked=True)).mappings().first()
                    if row is None:continue
                    subscriber=c.execute(select(subscriptions).where(subscriptions.c.id==row['subscription_id']).with_for_update()).mappings().first()
                    if subscriber is None:
                        c.execute(update(table).where(table.c.id==row['id']).values(status='cancelled',error='SUBSCRIPTION_MISSING'));continue
                    if table is verifications:
                        if subscriber['revision']!=row['revision']:
                            c.execute(update(table).where(table.c.id==row['id']).values(status='superseded'));continue
                        parsed=urlsplit(subscriber['callback']);query=parsed.query+('&' if parsed.query else '')+urlencode({'hub.mode':row['mode'],'hub.topic':subscriber['topic'],'hub.challenge':row['challenge'],**({'hub.lease_seconds':row['lease_seconds']} if row['mode']=='subscribe' else {})})
                        callback=urlunsplit((parsed.scheme,parsed.netloc,parsed.path,query,''))
                        verification_at=self.clock()
                        try:
                            with httpx.Client(timeout=self.timeout,transport=self.transport,trust_env=False,follow_redirects=False) as http:
                                response=http.get(callback)
                            if not response.is_success or response.content!=row['challenge'].encode():
                                if response.status_code>=500:raise ValueError('TRANSIENT_CALLBACK_ERROR')
                                c.execute(update(table).where(table.c.id==row['id']).values(status='denied',attempts=row['attempts']+1,error='CHALLENGE_REJECTED'));continue
                            c.execute(update(subscriptions).where(subscriptions.c.id==subscriber['id']).values(active=row['mode']=='subscribe',lease_until=verification_at+datetime.timedelta(seconds=row['lease_seconds']),secret=row['secret'] if row['mode']=='subscribe' else subscriber['secret']))
                            c.execute(update(table).where(table.c.id==row['id']).values(status='verified',attempts=row['attempts']+1,error=None));verified+=1
                        except Exception:c.execute(update(table).where(table.c.id==row['id']).values(**self.retry(row,'VERIFICATION_RETRY_REQUIRED')))
                    else:
                        topic_active=c.execute(select(topics.c.active).where(topics.c.name==subscriber['topic'])).scalar_one_or_none()
                        if not subscriber['active'] or subscriber['lease_until'] is None or subscriber['lease_until']<=self.clock() or topic_active is not True:
                            c.execute(update(table).where(table.c.id==row['id']).values(status='cancelled',error='SUBSCRIPTION_OR_TOPIC_INACTIVE'));continue
                        message=c.execute(select(messages).where(messages.c.id==row['message_id'])).mappings().first()
                        if message is None:
                            c.execute(update(table).where(table.c.id==row['id']).values(status='exhausted',error='MESSAGE_MISSING'));continue
                        canonical=str(httpx.URL(subscriber['topic'])) if urlsplit(subscriber['topic']).scheme in {'http','https'} else self.hub_url+'/topics/'+hashlib.sha256(subscriber['topic'].encode()).hexdigest()
                        headers={'content-type':message['content_type'],'link':'<'+self.hub_url+'/hub/>; rel="hub", <'+canonical+'>; rel="self"','x-karnatakadbt-delivery-id':row['id'],'idempotency-key':row['id']}
                        try:
                            if subscriber['secret']:
                                secret=self.cipher.decrypt(subscriber['secret'].encode());headers['x-hub-signature']='sha256='+hmac.new(secret,bytes(message['body']),hashlib.sha256).hexdigest()
                            with httpx.Client(timeout=self.timeout,transport=self.transport,trust_env=False,follow_redirects=False) as http:
                                response=http.post(subscriber['callback'],content=bytes(message['body']),headers=headers)
                            if not response.is_success:raise ValueError('DELIVERY_REJECTED')
                            c.execute(update(table).where(table.c.id==row['id']).values(status='delivered',attempts=row['attempts']+1,error=None));sent+=1
                        except Exception:c.execute(update(table).where(table.c.id==row['id']).values(**self.retry(row,'DELIVERY_RETRY_REQUIRED')))
        return {'verified':verified,'delivered':sent}

def create_hub_app(store,publisher_token,subscription_permits=(),workers_enabled=True,heartbeat=None):
    if not isinstance(publisher_token,str) or len(publisher_token)<32:raise ValueError('Strong publisher capability required')
    permits=list(subscription_permits)
    for item in permits:
        if not valid_topic(item['topic']) or not valid_callback(item['callback']) or len(item['token_sha256'])!=64:raise ValueError('Invalid subscription permit')
    stop=threading.Event();last_tick=[None]
    def work():
        while not stop.is_set():
            try:
                counts=store.tick()
                last_tick[0]=now()
                if heartbeat:heartbeat('RUNNING',counts)
            except Exception:
                if heartbeat:heartbeat('DEGRADED',{})
            stop.wait(1)
    @contextlib.asynccontextmanager
    async def lifespan(app):
        thread=threading.Thread(target=work,name='native-websub',daemon=True) if workers_enabled else None
        if thread:thread.start()
        yield
        stop.set()
        if thread:thread.join(timeout=25)
    app=FastAPI(title='KarnatakaDBT internal WebSub hub',docs_url=None,redoc_url=None,lifespan=lifespan)
    @app.middleware('http')
    async def headers(request,call_next):
        response=await call_next(request);response.headers['cache-control']='no-store';response.headers['x-content-type-options']='nosniff';return response
    @app.get('/health')
    def health():
        with store.engine.connect() as c:c.execute(select(topics.c.name).limit(1))
        if workers_enabled and (last_tick[0] is None or (now()-last_tick[0]).total_seconds()>60):raise HTTPException(503,'Hub worker is not healthy')
        return {'status':'UP','service':'native-websub'}
    @app.post('/hub/')
    async def hub(request:Request):
        content_type=request.headers.get('content-type','').split(';')[0]
        if content_type!='application/x-www-form-urlencoded':raise HTTPException(415,'Form encoding required')
        chunks=[];length=0
        async for chunk in request.stream():
            length+=len(chunk)
            if length>100*1024*1024:raise HTTPException(413,'Request is too large')
            chunks.append(chunk)
        try:form=parse_qs(b''.join(chunks).decode('utf-8'),keep_blank_values=True,max_num_fields=20)
        except Exception:raise HTTPException(400,'Invalid form encoding') from None
        if any(len(values)!=1 for values in form.values()):raise HTTPException(400,'Duplicate form parameters')
        form={key:values[0] for key,values in form.items()};mode=form.get('hub.mode');topic=form.get('hub.topic')
        if not valid_topic(topic):raise HTTPException(400,'Valid topic required')
        authorization=request.headers.get('authorization','');token=authorization[7:] if authorization.startswith('Bearer ') else ''
        if len(token)>512:raise HTTPException(401,'Invalid capability')
        if mode in {'subscribe','unsubscribe'}:
            callback=form.get('hub.callback','');digest=hashlib.sha256(token.encode()).hexdigest()
            if not any(item['topic']==topic and item['callback']==callback and hmac.compare_digest(item['token_sha256'],digest) for item in permits):raise HTTPException(403,'Subscription capability is not authorized')
            try:lease=int(form.get('hub.lease_seconds') or 86400)
            except ValueError:raise HTTPException(400,'Invalid lease duration') from None
            if lease<=0:raise HTTPException(400,'Positive lease required')
            secret=form.get('hub.secret') or ''
            if len(secret.encode())>200:raise HTTPException(400,'Subscription secret is too long')
            store.subscribe(topic,callback,mode,min(max(lease,60),864000),secret)
            return Response(status_code=202)
        if not hmac.compare_digest(token.encode(),publisher_token.encode()):raise HTTPException(401,'Publisher capability required')
        if mode in {'register','deregister'}:
            store.register(topic,mode=='register');return Response(status_code=204)
        if mode=='publish':
            body=form.get('hub.content')
            if body is None:raise HTTPException(400,'Direct notification content required')
            media=form.get('hub.content_type') or 'application/json'
            if media not in {'application/json','application/xml','text/plain','application/octet-stream'}:raise HTTPException(400,'Unsupported notification content type')
            return store.publish(topic,body.encode('utf-8'),media,request.headers.get('idempotency-key'))
        raise HTTPException(400,'Unsupported hub mode')
    return app
