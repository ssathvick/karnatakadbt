"""Durable HTTP audit records without request bodies, cookies or tokens."""
import datetime,uuid
from sqlalchemy import MetaData,Table,Column,String,Integer,insert,update

metadata=MetaData()
http_events=Table('console_http_events',metadata,
    Column('id',String,primary_key=True),Column('at',String,nullable=False),
    Column('path',String,nullable=False),Column('method',String,nullable=False),
    Column('actor',String),Column('status',Integer),Column('outcome',String,nullable=False))

class RegistryHttpAudit:
    def __init__(self,engine):self.engine=engine
    def initialize(self):metadata.create_all(self.engine)
    def begin(self,path,method):
        key=str(uuid.uuid4())
        with self.engine.begin() as c:
            c.execute(insert(http_events).values(id=key,at=datetime.datetime.now(datetime.timezone.utc).isoformat(),path=path,method=method,actor=None,status=None,outcome='PENDING'))
        return key
    def finish(self,key,actor,status,business_error=False):
        outcome='DENIED' if status in {401,403} else ('FAILURE' if status>=400 or business_error else 'SUCCESS')
        with self.engine.begin() as c:
            c.execute(update(http_events).where(http_events.c.id==key).values(actor=actor,status=status,outcome=outcome))
