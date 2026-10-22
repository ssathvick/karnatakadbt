"""Indexed custom registry state rows with namespace-scoped stable keys."""
import datetime,hashlib,json
from pathlib import Path
from sqlalchemy import MetaData,Table,Column,String,BigInteger,DateTime,Identity,Index,select,insert,update
from sqlalchemy.dialects.postgresql import JSONB
from registry_message_template_store import RegistryMessageTemplateStore

metadata=MetaData()
rows=Table('console_registry_rows',metadata,
    Column('kind',String,primary_key=True),Column('key',String,primary_key=True),
    Column('register_id',String),Column('record_id',String),Column('link_id',String),Column('section_id',String),Column('status',String),Column('at',DateTime(timezone=True)),
    Column('sequence',BigInteger,Identity(),nullable=False),Column('data',JSONB,nullable=False))
Index('ix_console_rows_record',rows.c.kind,rows.c.register_id,rows.c.record_id,rows.c.section_id)
Index('ix_console_rows_link',rows.c.kind,rows.c.link_id)
Index('ix_console_rows_status_time',rows.c.kind,rows.c.status,rows.c.at)
for field in ['change_request_id','submission_id']:
    Index('ix_console_rows_'+field,rows.c.kind,rows.c.data[field].astext)

class RegistryRowStore(RegistryMessageTemplateStore):
    def initialize(self):
        super().initialize();metadata.create_all(self.engine)
        for index in rows.indexes:index.create(self.engine,checkfirst=True)
    def row_key(self,kind,row):
        contract=json.loads(Path(__file__).with_name('registry_row_contract.json').read_text())[kind]
        return hashlib.sha256(json.dumps([row[key] for key in contract['primary_key']],sort_keys=True,default=str).encode()).hexdigest()
    def row_attributes(self,kind,row):
        stamp=row.get('created_at') or row.get('computed_at') or row.get('verified_at') or row.get('first_created_at')
        if stamp:
            stamp=datetime.datetime.fromisoformat(str(stamp).replace('Z','+00:00'))
            if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=datetime.timezone.utc)
        return {'register_id':row.get('register_id'),'record_id':row.get('internal_record_id'),'link_id':row.get('link_internal_record_id'),'section_id':row.get('section_id'),'status':row.get('approval_status'),'at':stamp}
    def put_row(self,c,kind,row,new=False):
        key=self.row_key(kind,row);attrs=self.row_attributes(kind,row)
        if new:c.execute(insert(rows).values(kind=kind,key=key,data=row,**attrs))
        else:c.execute(update(rows).where(rows.c.kind==kind,rows.c.key==key).values(data=row,**attrs))
    def state_rows(self,c,kind,**filters):
        query=select(rows.c.data).where(rows.c.kind==kind)
        for field,value in filters.items():query=query.where(rows.c[field]==value)
        return [dict(row) for row in c.execute(query.order_by(rows.c.sequence)).scalars()]
    def seed_rows(self,dataset):
        with self.engine.begin() as c:
            for kind,data in dataset.items():
                if c.execute(select(rows.c.key).where(rows.c.kind==kind).limit(1)).first():raise RuntimeError('Refusing to overwrite registry rows: '+kind)
                for row in data:self.put_row(c,kind,row,True)
