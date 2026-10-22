"""Own provider summaries and beneficiary authentication history read models."""
from sqlalchemy import MetaData,Table,Column,String,Boolean,Integer,DateTime,Index,select
from sqlalchemy.dialects.postgresql import JSONB
from registry_search_store import RegistrySearchStore
from registry_record_store import record_timestamp

metadata=MetaData()
auth_views=Table('console_registrant_auth_views',metadata,Column('kind',String,primary_key=True),Column('id',String,primary_key=True),Column('register_id',String),Column('record_id',String),Column('initiated_at',DateTime),Column('is_active',Boolean),Column('display_order',Integer),Column('data',JSONB,nullable=False))
Index('ix_console_registrant_auth_history',auth_views.c.kind,auth_views.c.record_id,auth_views.c.initiated_at)
Index('ix_console_registrant_auth_providers',auth_views.c.kind,auth_views.c.register_id,auth_views.c.is_active,auth_views.c.display_order)
SUPPORTED_PATHS=frozenset('/register-data/'+name for name in ['get_available_authentication_providers','get_registrant_authentication_status','get_registrant_authentication_history'])
PROVIDER_FIELDS=['provider_id','register_id','provider_name','provider_description','adapter_name','display_order','is_active']
HISTORY_FIELDS=['authentication_id','register_id','internal_record_id','initiated_at','status','authentication_method','initiated_by_staff_id','claim_verifications','expiry_at','failure_reason']

class RegistryRegistrantViewStore(RegistrySearchStore):
    def initialize(self):super().initialize();metadata.create_all(self.engine)
    def auth_view_values(self,kind,value):
        allowed=PROVIDER_FIELDS if kind=='provider' else HISTORY_FIELDS
        if set(value)-set(allowed):raise ValueError('Authentication read views must not contain provider secrets or raw identity tokens')
        return {'kind':kind,'id':value['provider_id' if kind=='provider' else 'authentication_id'],'register_id':value['register_id'],'record_id':value.get('internal_record_id'),'initiated_at':record_timestamp(value['initiated_at']) if value.get('initiated_at') else None,'is_active':value.get('is_active'),'display_order':value.get('display_order'),'data':value}
    def execute_request(self,path,p,actor,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_request(path,p,actor,pagination)
        with self.engine.connect() as c:
            if path.endswith('/get_available_authentication_providers'):
                values=c.execute(select(auth_views.c.data).where(auth_views.c.kind=='provider',auth_views.c.register_id==p['register_id'],auth_views.c.is_active.is_(True)).order_by(auth_views.c.display_order.asc())).scalars()
                return {'providers':[self.models.model('RegistrantAuthProviderSummary').model_validate(value).model_dump(mode='json') for value in values]},None
            status=path.endswith('/get_registrant_authentication_status')
            values=list(c.execute(select(auth_views.c.data).where(auth_views.c.kind=='history',auth_views.c.record_id==p['internal_record_id']).order_by(auth_views.c.initiated_at.desc()).limit(1 if status else 50)).scalars())
            output=[self.models.model('RegistrantAuthHistoryItem').model_validate(value).model_dump(mode='json') for value in values]
            # A status view reports the most recent attempt, including a failed
            # or expired attempt, just like the retained console contract.
            return {'authentication':output[0] if output else None} if status else {'authentications':output},None
