"""Native outgoing transformations and WebSub dispatch with durable state."""
import json
from copy import deepcopy
from urllib.parse import urlsplit
import httpx
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy import MetaData,Table,Column,String,select,insert,update
from sqlalchemy.dialects.postgresql import JSONB
from registry_native_workers import WorkerFailure
from registry_message_data_store import messages
from registry_message_template_store import templates
from registry_document_store import documents

metadata=MetaData()
outputs=Table('native_registry_worker_outputs',metadata,Column('kind',String,primary_key=True),Column('key',String,primary_key=True),Column('data',JSONB,nullable=False))
TASKS=frozenset({'outgest_data_transformation_worker','outgest_data_publish_worker','outgest_topic_register_worker'})

class NativeWebsub:
    def __init__(self,endpoint,allowed_origins,transport=None,publisher_token=None):
        parsed=urlsplit(endpoint);origin=parsed.scheme+'://'+parsed.netloc
        if origin not in allowed_origins or parsed.scheme not in {'http','https'} or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Explicit trusted WebSub origin required')
        if publisher_token is not None and (not isinstance(publisher_token,str) or len(publisher_token)<32):raise ValueError('Strong publisher capability required')
        self.url=endpoint.rstrip('/')+'/hub/';self.transport=transport;self.publisher_token=publisher_token
    def __call__(self,action,topic,payload=None):
        return self.send_with_key(action,topic,payload)
    def send_with_key(self,action,topic,payload=None,idempotency_key=None):
        if action not in {'register','publish','deregister'}:raise ValueError('Invalid WebSub action')
        body={'hub.mode':action,'hub.topic':topic}
        if action=='publish':body['hub.content']=json.dumps(payload)
        headers={}
        if self.publisher_token:headers['authorization']='Bearer '+self.publisher_token
        if idempotency_key:headers['idempotency-key']=idempotency_key
        with httpx.Client(transport=self.transport,timeout=15,trust_env=False,follow_redirects=False) as client:
            response=client.post(self.url,data=body,headers=headers)
            if not 200<=response.status_code<300:raise WorkerFailure('WEBSUB_DISPATCH_REJECTED')

def render_outgoing(template,data):
    if not isinstance(template,str) or len(template)>2*1024*1024:raise WorkerFailure('OUTGOING_TEMPLATE_INVALID')
    # Template content can read supplied JSON only, never arbitrary Python attributes.
    environment=SandboxedEnvironment()
    rendered=environment.from_string(template).render(expanded=data)
    if len(rendered)>32*1024*1024:raise WorkerFailure('OUTGOING_PAYLOAD_TOO_LARGE')
    return json.loads(rendered)

class NativeOutgoingWorkers:
    def __init__(self,store,websub=None,max_attempts=3):
        if not isinstance(max_attempts,int) or max_attempts<1:raise ValueError('Positive attempt limit required')
        self.store,self.websub,self.max_attempts=store,websub,max_attempts
    def initialize(self):metadata.create_all(self.store.engine)
    def run(self,task,key):
        if task not in TASKS:raise ValueError('Unimplemented outgoing worker')
        kind='topic' if task=='outgest_topic_register_worker' else 'outgoing'
        prefix='websub_register' if kind=='topic' else 'transformation' if task=='outgest_data_transformation_worker' else 'publish'
        with self.store.engine.begin() as c:
            value=c.execute(select(messages.c.data).where(messages.c.kind==kind,messages.c.key==key).with_for_update()).scalar_one_or_none()
            if value is None:return {'status':'NOT_FOUND'}
            value=deepcopy(value)
            if value.get(prefix+'_status')!='PENDING':return {'status':value.get(prefix+'_status'),'skipped':True}
            if (value.get(prefix+'_number_of_attempts') or 0)>=self.max_attempts:value[prefix+'_status']='FAILED'
            else:
                try:
                    with c.begin_nested():
                        if kind=='topic':self._send('register',value.get('websub_topic'))
                        elif task=='outgest_data_transformation_worker':self._transform(c,value)
                        else:
                            if value.get('transformation_status')!='PROCESSED':return {'status':'PENDING','skipped':True}
                            topic=self.store.message(c,'topic',value['topic_id'])
                            payload=c.execute(select(outputs.c.data).where(outputs.c.kind=='outgoing-transformed',outputs.c.key==key)).scalar_one_or_none()
                            if not topic or not payload:raise WorkerFailure('OUTGOING_PUBLICATION_INPUT_MISSING')
                            self._send('publish',topic.get('websub_topic'),payload['transformed_data_json'],key=value['outgest_id'])
                    value[prefix+'_status']='PROCESSED';value[prefix+'_latest_error_code']=None
                except Exception as error:
                    value[prefix+'_latest_error_code']=str(error) if isinstance(error,WorkerFailure) else 'OUTGOING_WORKER_FAILED'
                    value[prefix+'_status']='FAILED' if (value.get(prefix+'_number_of_attempts') or 0)+1>=self.max_attempts else 'PENDING'
                value[prefix+'_number_of_attempts']=(value.get(prefix+'_number_of_attempts') or 0)+1
                value[prefix+'_datetime']=self.store.clock().replace(tzinfo=None).isoformat()
            c.execute(update(messages).where(messages.c.kind==kind,messages.c.key==key).values(data=value))
            return {'status':value[prefix+'_status'],'attempts':value.get(prefix+'_number_of_attempts',0),'error':value.get(prefix+'_latest_error_code')}
    def _send(self,action,topic,payload=None,key=None):
        if not isinstance(topic,str) or not topic:raise WorkerFailure('OUTGOING_TOPIC_MISSING')
        if not callable(self.websub):raise WorkerFailure('WEBSUB_NOT_CONFIGURED')
        if key and hasattr(self.websub,'send_with_key'):self.websub.send_with_key(action,topic,payload,idempotency_key=key)
        else:self.websub(action,topic,payload)
    def _transform(self,c,value):
        matches=list(c.execute(select(templates.c.data).where(templates.c.kind=='outgoing',templates.c.data['data_model_id'].as_string()==value['data_model_id'],templates.c.data['register_id'].as_string()==value['register_id'])).scalars())
        if len(matches)!=1:raise WorkerFailure('OUTGOING_TEMPLATE_NOT_UNIQUE')
        document=c.execute(select(documents.c.data).where(documents.c.kind=='catalog',documents.c.id==matches[0]['template_document_id'],documents.c.state=='READY')).scalar_one_or_none()
        raw=self.store.message(c,'outgoing-payload',value['payload_id'])
        if not document or raw is None:raise WorkerFailure('OUTGOING_TRANSFORMATION_INPUT_MISSING')
        template=self.store.storage.get_bytes(document['document_store_id'],document['bucket']).decode('utf-8')
        transformed=render_outgoing(template,raw['raw_data_json'])
        output={field:value.get(field) for field in ['outgest_id','payload_id','change_request_id','intake_form_submission_id']}
        output['transformed_data_json']=transformed
        output['transformed_data_xml']=None
        existing=c.execute(select(outputs.c.key).where(outputs.c.kind=='outgoing-transformed',outputs.c.key==value['outgest_id'])).first()
        if existing:c.execute(update(outputs).where(outputs.c.kind=='outgoing-transformed',outputs.c.key==value['outgest_id']).values(data=output))
        else:c.execute(insert(outputs).values(kind='outgoing-transformed',key=value['outgest_id'],data=output))
        value['publish_status']='PENDING'
