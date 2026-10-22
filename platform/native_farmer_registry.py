"""Dedicated farmer records; no implicit linkage to household/person registries.

Callers must authorize staff access before invoking writes. This module does
not expose an unauthenticated HTTP interface or activate payment processing.
"""
import datetime
import math
import uuid
from sqlalchemy import MetaData,Table,Column,String,Integer,JSON,select,insert,update

metadata=MetaData(schema='kdbt_farmer_registry')
records=Table('records',metadata,Column('farmer_id',String,primary_key=True),Column('revision',Integer,nullable=False),Column('data',JSON,nullable=False))
history=Table('history',metadata,Column('event_id',String,primary_key=True),Column('farmer_id',String,nullable=False),Column('revision',Integer,nullable=False),Column('actor',String,nullable=False),Column('record',JSON,nullable=False),Column('at',String,nullable=False))
FIELDS=frozenset({'name','link_registry_id','registration_date','land_area','no_of_cattle_heads','no_of_poultry_heads','large_area_id','large_area_code','small_area_id','small_area_code'})

class FarmerRegistry:
    def __init__(self,engine):self.engine=engine
    def initialize(self):metadata.create_all(self.engine)
    @staticmethod
    def validate(data):
        if not isinstance(data,dict) or set(data)-FIELDS:raise ValueError('Unknown farmer fields')
        result=dict(data)
        for name in ['name','large_area_id','large_area_code','small_area_id','small_area_code']:
            if not isinstance(result.get(name),str) or not result[name].strip() or len(result[name])>256:raise ValueError('Complete farmer identity and geography required')
            result[name]=result[name].strip()
        if result.get('link_registry_id') is not None:
            if not isinstance(result['link_registry_id'],str) or not result['link_registry_id'].strip():raise ValueError('Explicit linked registry identifier required')
        datetime.date.fromisoformat(result['registration_date'])
        for name in ['no_of_cattle_heads','no_of_poultry_heads']:
            value=result.get(name,0)
            if type(value) is not int or value<0:raise ValueError('Nonnegative livestock count required')
            result[name]=value
        value=result.get('land_area',0)
        if type(value) not in {int,float} or not math.isfinite(value) or value<0:raise ValueError('Finite nonnegative land area required')
        result['land_area']=value
        return result
    def save(self,farmer_id,data,*,actor,expected_revision):
        if not isinstance(actor,str) or not actor.strip():raise ValueError('Authenticated audit actor required')
        if not isinstance(farmer_id,str) or not farmer_id.strip() or len(farmer_id)>256:raise ValueError('Farmer identifier required')
        if type(expected_revision) is not int or expected_revision<0:raise ValueError('Expected revision required')
        data=self.validate(data)
        with self.engine.begin() as c:
            revision=expected_revision+1
            if expected_revision==0:c.execute(insert(records).values(farmer_id=farmer_id,revision=revision,data=data))
            else:
                changed=c.execute(update(records).where(records.c.farmer_id==farmer_id,records.c.revision==expected_revision).values(revision=revision,data=data))
                if changed.rowcount!=1:raise ValueError('Farmer revision conflict')
            c.execute(insert(history).values(event_id=str(uuid.uuid4()),farmer_id=farmer_id,revision=revision,actor=actor,record=data,at=datetime.datetime.now(datetime.timezone.utc).isoformat()))
        return revision
    def geography(self,c,identifier):
        row=c.execute(select(records.c.data).where(records.c.farmer_id==identifier)).scalar_one_or_none()
        if row is None:raise ValueError('Dedicated farmer record required')
        return dict(administrative_zone_id_large=row['large_area_id'],administrative_zone_mnemonic_large=row['large_area_code'],administrative_zone_id_small=row['small_area_id'],administrative_zone_mnemonic_small=row['small_area_code'])
    def get(self,identifier):
        with self.engine.connect() as c:
            row=c.execute(select(records).where(records.c.farmer_id==identifier)).mappings().first()
            return dict(row) if row else None
    def list(self,*,offset=0,limit=25):
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:raise ValueError('Bounded pagination required')
        with self.engine.connect() as c:return [dict(row) for row in c.execute(select(records).order_by(records.c.farmer_id).offset(offset).limit(limit)).mappings()]
    def revisions(self,identifier):
        with self.engine.connect() as c:return [dict(row) for row in c.execute(select(history).where(history.c.farmer_id==identifier).order_by(history.c.revision)) .mappings()]
