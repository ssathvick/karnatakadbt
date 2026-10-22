"""Custom outgoing topic configuration and registration state transitions."""
import uuid
from sqlalchemy import Index,select,insert,update,delete,func
from registry_subscription_store import RegistrySubscriptionStore
from registry_message_data_store import messages
from registry_configuration_store import catalog

topic_unique=Index('ux_console_message_topic_register_model',messages.c.data['register_id'].astext,messages.c.data['data_model_id'].astext,unique=True,postgresql_where=messages.c.kind=='topic')
SUPPORTED_PATHS=frozenset('/outgestion-config/'+name for name in ['create_topic','get_topic','get_all_topics','update_topic','toggle_topicstatus','re_register_topic','delete_topic'])

class RegistryTopicStore(RegistrySubscriptionStore):
    def initialize(self):super().initialize();topic_unique.create(self.engine,checkfirst=True)
    def topic_definition(self,c,kind,key):
        value=self.definition(c,kind,key)
        if value is None:self.fail('REGISTER_NOT_FOUND' if kind=='register' else 'DATA_MODEL_NOT_FOUND')
        return value
    def topic_wire(self,c,value,definitions=None):
        def linked(kind,key):
            if definitions is None:return self.topic_definition(c,kind,key)
            result=definitions.get((kind,key))
            if result is None:self.fail('REGISTER_NOT_FOUND' if kind=='register' else 'DATA_MODEL_NOT_FOUND')
            return result
        register=linked('register',value['register_id']);model=linked('model',value['data_model_id'])
        # The source DTO's validation alias discards the service's message
        # argument. Preserve its null wire value and retain the stored code.
        return self.models.model('OutgoingTopicData').model_validate({**value,'register_mnemonic':register['register_mnemonic'],'data_model_mnemonic':model['data_model_mnemonic'],'websub_register_latest_error_message':None}).model_dump(mode='json')
    def topic(self,c,key):
        if not key:self.fail('INVALID_REQUEST')
        value=self.message(c,'topic',key)
        if value is None:self.fail('TOPIC_NOT_FOUND')
        return dict(value)
    def execute_request(self,path,p,actor,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_request(path,p,actor,pagination)
        op=path.rsplit('/',1)[-1];reading=op.startswith('get_')
        with (self.engine.connect() if reading else self.write()) as c:
            if op=='get_all_topics':
                page=pagination or {};current=page.get('current_page') or 1;size=page.get('page_size') or 10
                count=c.execute(select(func.count()).select_from(messages).where(messages.c.kind=='topic')).scalar_one()
                values=list(c.execute(select(messages.c.data).where(messages.c.kind=='topic').order_by(messages.c.key).offset((current-1)*size).limit(size)).scalars())
                keys={value[field] for value in values for field in ['register_id','data_model_id']}
                definitions={(kind,key):value for kind,key,value in c.execute(select(catalog.c.kind,catalog.c.id,catalog.c.data).where(catalog.c.kind.in_(['register','model']),catalog.c.id.in_(keys)))} if keys else {}
                return [self.topic_wire(c,value,definitions) for value in values],{'number_of_items':count,'number_of_pages':(count+size-1)//size if count else 0}
            if op=='create_topic':
                self.topic_definition(c,'register',p['register_id']);self.topic_definition(c,'model',p['data_model_id'])
                if not p['register_id'] or not p['data_model_id'] or not p['websub_topic']:self.fail('INVALID_REQUEST')
                existing=c.execute(select(messages.c.key).where(messages.c.kind=='topic',messages.c.data['register_id'].astext==p['register_id'],messages.c.data['data_model_id'].astext==p['data_model_id'])).first()
                if existing:self.fail('TOPIC_ALREADY_EXISTS')
                key=p.get('topic_id') or str(uuid.uuid4());value={field:p.get(field) for field in ['register_id','data_model_id','websub_topic','description']}
                value.update(topic_id=key,is_active=True,created_at=self.clock().isoformat(),updated_at=None,websub_register_status='PENDING',websub_register_datetime=None,websub_register_number_of_attempts=0,websub_register_latest_error_code=None)
                c.execute(insert(messages).values(kind='topic',key=key,data=value))
            else:
                key=p['topic_id'];value=self.topic(c,key)
                if op=='get_topic':return self.topic_wire(c,value),None
                if op=='delete_topic':
                    if value['is_active']:self.fail('TOPIC_NOT_INACTIVE')
                    result=self.topic_wire(c,value);c.execute(delete(messages).where(messages.c.kind=='topic',messages.c.key==key));self.record(c,actor,op,key,{'topic_id':key});return result,None
                if op=='update_topic':
                    for field,kind in [('register_id','register'),('data_model_id','model')]:
                        if p.get(field) is not None:self.topic_definition(c,kind,p[field]);value[field]=p[field]
                    if p.get('description') is not None:value['description']=p['description']
                else:
                    if op=='toggle_topicstatus':value['is_active']=not value['is_active']
                    value.update(websub_register_status='PENDING',websub_register_number_of_attempts=0,updated_at=self.clock().isoformat())
                c.execute(update(messages).where(messages.c.kind=='topic',messages.c.key==key).values(data=value))
            result=self.topic_wire(c,value);self.record(c,actor,op,key,{'topic_id':key});return result,None
