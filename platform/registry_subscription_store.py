"""Custom partner subscription activity and its durable console history."""
import datetime,uuid
import httpx
from sqlalchemy import MetaData,Table,Column,String,DateTime,Index,select,insert,func
from sqlalchemy.dialects.postgresql import JSONB
from registry_message_data_store import RegistryMessageDataStore

metadata=MetaData()
subscriptions=Table('console_subscription_activity',metadata,Column('id',String,primary_key=True),Column('partner_id',String,nullable=False),Column('at',DateTime,nullable=False),Column('data',JSONB,nullable=False))
Index('ix_console_subscription_partner_time',subscriptions.c.partner_id,subscriptions.c.at)
Index('ix_console_subscription_time',subscriptions.c.at)
SUPPORTED_PATHS=frozenset('/ingestion-config/'+name for name in ['create_subscription_activity_log','get_subscription_activity_logs_by_partner','get_all_subscription_activity_logs'])

class RegistrySubscriptionStore(RegistryMessageDataStore):
    def __init__(self,engine,storage=None,clock=None,subscription_transport=None):
        super().__init__(engine,storage,clock);self.subscription_transport=subscription_transport
    def initialize(self):
        super().initialize();metadata.create_all(self.engine)
        for index in subscriptions.indexes:index.create(self.engine,checkfirst=True)
    def subscription_wire(self,value):return self.models.model('SubscriptionActivityLogData').model_validate(value).model_dump(mode='json')
    def seed_subscriptions(self,values):
        with self.engine.begin() as c:
            if c.execute(select(subscriptions.c.id).limit(1)).first():raise RuntimeError('Refusing to overwrite subscription history')
            for value in values:c.execute(insert(subscriptions).values(id=value['subscription_activity_log_id'],partner_id=value['partner_id'],at=datetime.datetime.fromisoformat(value['date_time']),data=value))
    def execute_request(self,path,p,actor,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_request(path,p,actor,pagination)
        op=path.rsplit('/',1)[-1]
        if op=='create_subscription_activity_log':
            # Partner requests happen before the SQL transaction, matching the
            # existing contract. Never hold registry row locks over network IO.
            try:
                with httpx.Client(timeout=30,trust_env=False,transport=self.subscription_transport) as client:
                    response=client.post(p['subscription_url'],headers=p.get('header') or {},json=p.get('payload') or {})
                    response.raise_for_status();result=response.json() if response.text else None
            except Exception as error:self.fail('SUBSCRIPTION_CALL_FAILED','Failed to call subscription URL: '+str(error))
            value={key:p.get(key) for key in ['is_unsubscribe','description','partner_id','subscription_url','registry_callback_url','header','payload']}
            value.update(subscription_activity_log_id=str(uuid.uuid4()),date_time=self.clock().isoformat(),response=result)
            with self.engine.begin() as c:
                c.execute(insert(subscriptions).values(id=value['subscription_activity_log_id'],partner_id=value['partner_id'],at=datetime.datetime.fromisoformat(value['date_time']),data=value))
                self.record(c,actor,op,value['subscription_activity_log_id'],{'subscription_activity_log_id':value['subscription_activity_log_id']})
            return [self.subscription_wire(value)],None
        with self.engine.connect() as c:
            query=select(subscriptions.c.data).order_by(subscriptions.c.at.desc())
            if op=='get_subscription_activity_logs_by_partner':return [self.subscription_wire(value) for value in c.execute(query.where(subscriptions.c.partner_id==p['partner_id'])).scalars()],None
            page=pagination or {};current=page.get('current_page') or 1;size=page.get('page_size') or 10
            count=c.execute(select(func.count()).select_from(subscriptions)).scalar_one()
            return [self.subscription_wire(value) for value in c.execute(query.offset((current-1)*size).limit(size)).scalars()],{'number_of_items':count,'number_of_pages':(count+size-1)//size if count else 0}
