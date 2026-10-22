"""Independent DBT domain storage. No ORM/RPC or runtime dependency on Odoo."""
import datetime,hashlib,json
from decimal import Decimal,InvalidOperation
from pathlib import Path
from sqlalchemy import (create_engine,MetaData,Table,Column,String,Integer,BigInteger,JSON,ForeignKey,UniqueConstraint,Index,select,insert,update,func)
from sqlalchemy.exc import IntegrityError
from programme_rules import validate_rules,evaluate_rules,today

metadata=MetaData()
entities=Table('registry_entities',metadata,Column('reference',String(160),primary_key=True),Column('kind',String(24),nullable=False),Column('name',String(300),nullable=False),Column('subject',String(160)),Column('household_ref',String(160)),Column('district_id',String(64)),Column('attributes',JSON,nullable=False),Column('source_version',String(100)),Column('updated_at',String(64),nullable=False))
programmes=Table('programmes',metadata,Column('id',Integer,primary_key=True),Column('mnemonic',String(100),nullable=False,unique=True),Column('name',String(300),nullable=False),Column('amount_minor',BigInteger,nullable=False),Column('income_limit_minor',BigInteger,nullable=False),Column('min_members',Integer,nullable=False),Column('status',String(30),nullable=False),Column('configuration',JSON,nullable=False),Column('version',Integer,nullable=False,default=1))
applications=Table('programme_applications',metadata,Column('id',Integer,primary_key=True,autoincrement=False),Column('subject',String(160),nullable=False),Column('household_ref',String(160),nullable=False),Column('programme_id',Integer,ForeignKey('programmes.id'),nullable=False),Column('status',String(40),nullable=False),Column('eligibility',JSON),Column('version',Integer,nullable=False,default=1),Column('updated_at',String(64),nullable=False),UniqueConstraint('subject','programme_id'))
batches=Table('beneficiary_batches',metadata,Column('id',String(100),primary_key=True),Column('programme_id',Integer),Column('workflow_status',String(60)),Column('eligibility_status',String(60)),Column('entitlement_status',String(60)),Column('instruction_status',String(60)),Column('details',JSON,nullable=False))
history=Table('migration_records',metadata,Column('record_key',String(300),primary_key=True),Column('source',String(60),nullable=False),Column('entity',String(100),nullable=False),Column('source_id',String(100),nullable=False),Column('payload',JSON,nullable=False),Column('sha256',String(64),nullable=False))
events=Table('domain_events',metadata,Column('id',String(100),primary_key=True),Column('aggregate',String(180),nullable=False),Column('action',String(80),nullable=False),Column('actor',String(160),nullable=False),Column('payload',JSON,nullable=False),Column('at',String(64),nullable=False))
outbox=Table('projection_outbox',metadata,Column('key',String(180),primary_key=True),Column('kind',String(60),nullable=False),Column('payload',JSON,nullable=False),Column('status',String(30),nullable=False),Column('attempts',Integer,nullable=False,default=0),Column('error',String(250)),Column('updated_at',String(64),nullable=False))
Index('ix_registry_kind_subject',entities.c.kind,entities.c.subject)
Index('ix_registry_household',entities.c.household_ref)
Index('ix_applications_subject_status',applications.c.subject,applications.c.status)
Index('ix_migration_collection',history.c.source,history.c.entity)
Index('ix_outbox_status',outbox.c.status)
Index('ix_domain_events_at',events.c.at)

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def minor(value):
    try:
        value=Decimal(str(value))
        if not value.is_finite() or value<0 or value*100 != (value*100).to_integral_value():raise ValueError('Use a finite non-negative amount with at most two decimal places.')
        return int(value*100)
    except InvalidOperation:raise ValueError('Invalid currency amount.')
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()

class DomainConflict(ValueError):pass

class CoreStore:
    def __init__(self,url):
        options={'pool_pre_ping':True,'hide_parameters':True}
        if url.startswith('sqlite'):options['connect_args']={'check_same_thread':False,'timeout':30}
        self.engine=create_engine(url,**options)

    def migrate(self):
        from alembic import command
        from alembic.config import Config
        config=Config();config.set_main_option('script_location',str(Path(__file__).with_name('core_migrations')))
        with self.engine.begin() as conn:config.attributes['connection']=conn;command.upgrade(config,'head')

    def put(self,c,table,key,values):
        # Atomic database-specific upsert; no select-then-insert race.
        if self.engine.dialect.name=='postgresql':from sqlalchemy.dialects.postgresql import insert as upsert
        else:from sqlalchemy.dialects.sqlite import insert as upsert
        statement=upsert(table).values(**values)
        c.execute(statement.on_conflict_do_update(index_elements=[table.c[key]],set_={k:getattr(statement.excluded,k) for k in values if k!=key}))

    def event(self,c,key,aggregate,action,actor,payload):
        if not c.execute(select(events.c.id).where(events.c.id==key)).first():
            c.execute(insert(events).values(id=key,aggregate=aggregate,action=action,actor=actor,payload=payload,at=now()))

    def registry(self,household,data,subject,version,actor):
        with self.engine.begin() as c:
            self.put(c,entities,'reference',dict(reference=household,kind='household',name=data['household_name'],subject=subject,household_ref=household,district_id=data['state'],attributes=data,source_version=version,updated_at=now()))
            active=set()
            for m in data['members']:
                active.add(m['ref'])
                self.put(c,entities,'reference',dict(reference=m['ref'],kind='individual',name=m['given']+' '+m['family'],subject=None,household_ref=household,district_id=data['state'],attributes={**m,'active':True},source_version=version,updated_at=now()))
            for prior in c.execute(select(entities).where(entities.c.household_ref==household,entities.c.kind=='individual')).mappings():
                if prior['reference'] not in active:c.execute(update(entities).where(entities.c.reference==prior['reference']).values(attributes={**prior['attributes'],'active':False},updated_at=now()))
            self.put(c,outbox,'key',dict(key='registry:'+household,kind='registry',payload={'subject':subject,'reference':household,'version':version},status='pending',attempts=0,error=None,updated_at=now()))
            self.event(c,'registry:'+household+':'+version,household,'registry_synchronized',actor,{'members':len(active),'source_version':version})

    def create_programme(self,mnemonic,name,amount,income,minimum,actor,rules=None):
        rules=validate_rules(rules,minimum)
        if not name or not 1<=minimum<=8 or not 0<minor(amount)<=100000000 or minor(income)>100000000000:raise ValueError('Check programme limits.')
        try:
            with self.engine.begin() as c:
                old=c.execute(select(programmes).where(programmes.c.mnemonic==mnemonic)).mappings().first()
                if old:raise DomainConflict('This programme mnemonic already exists.')
                pid=c.execute(insert(programmes).values(mnemonic=mnemonic,name=name,amount_minor=minor(amount),income_limit_minor=minor(income),min_members=minimum,status='ACTIVE',configuration={'target':'household','eligibility':'monthly_income_and_size','currency':'INR','rule_version':1,'synthetic':True,'rules':rules},version=1).returning(programmes.c.id)).scalar_one()
                self.put(c,outbox,'key',dict(key='programme:'+str(pid),kind='programme',payload={'id':pid},status='pending',attempts=0,error=None,updated_at=now()))
                self.event(c,'programme:'+str(pid)+':1','programme:'+str(pid),'programme_created',actor,{'mnemonic':mnemonic,'amount_minor':minor(amount),'income_limit_minor':minor(income),'min_members':minimum,'rules':rules})
                return pid
        except IntegrityError:raise DomainConflict('This programme mnemonic already exists.') from None

    def application(self,app,household,actor):
        with self.engine.begin() as c:
            old=c.execute(select(applications).where(applications.c.id==app['id'])).mappings().first()
            if not old:
                c.execute(insert(applications).values(id=app['id'],subject=app['sub'],household_ref=household,programme_id=app['program'],status=app['status'],eligibility=None,version=1,updated_at=now()))
                self.event(c,'application:'+str(app['id'])+':submitted',household,'application_submitted',actor,{'application':app['id'],'programme':app['program']})

    def update_programme(self,pid,version,name,amount,income,minimum,status,actor,rules=None):
        if not name or not 1<=minimum<=8 or status not in ['ACTIVE','PAUSED','CLOSED'] or not 0<minor(amount)<=100000000 or minor(income)>100000000000:raise ValueError('Check programme configuration.')
        with self.engine.begin() as c:
            old=c.execute(select(programmes).where(programmes.c.id==pid).with_for_update()).mappings().first()
            if not old:raise DomainConflict('Programme not found.')
            if old['version']!=version:raise DomainConflict('Programme changed. Reload before saving.')
            rules=validate_rules(old['configuration'].get('rules',{}) if rules is None else rules,minimum)
            c.execute(update(programmes).where(programmes.c.id==pid).values(name=name,amount_minor=minor(amount),income_limit_minor=minor(income),min_members=minimum,status=status,configuration={**old['configuration'],'rule_version':version+1,'rules':rules},version=version+1))
            self.put(c,outbox,'key',dict(key='programme:'+str(pid),kind='programme',payload={'id':pid},status='pending',attempts=0,error=None,updated_at=now()))
            self.event(c,'programme:'+str(pid)+':'+str(version+1),'programme:'+str(pid),'programme_updated',actor,{'status':status,'amount_minor':minor(amount),'income_limit_minor':minor(income),'min_members':minimum,'rules':rules,'version':version+1})

    def decide(self,aid,action,actor):
        with self.engine.begin() as c:
            app=c.execute(select(applications).where(applications.c.id==aid).with_for_update()).mappings().first()
            if not app:raise DomainConflict('Application not found.')
            programme=c.execute(select(programmes).where(programmes.c.id==app['programme_id']).with_for_update()).mappings().one()
            eligibility=app['eligibility']
            if programme['status']!='ACTIVE':raise DomainConflict('The programme is not active.')
            if action=='check' and app['status'] in ['pending_review','checking_eligibility','eligible','not_eligible']:
                household=c.execute(select(entities).where(entities.c.reference==app['household_ref']).with_for_update()).mappings().first()
                if not household:raise DomainConflict('Synchronize the approved household before eligibility assessment.')
                data=household['attributes'];members=data['members']
                checks=[{'rule':'Monthly household income','actual_minor':minor(data['monthly_income']),'ceiling_minor':programme['income_limit_minor'],'passed':minor(data['monthly_income'])<=programme['income_limit_minor']},{'rule':'Minimum household members','actual':len(members),'minimum':programme['min_members'],'passed':len(members)>=programme['min_members']}]
                checks+=evaluate_rules(data,programme['configuration'].get('rules',{}))
                eligibility={'assessed_on':today().isoformat(),'rule_version':programme['configuration'].get('rule_version',1),'checks':checks,'eligible':all(x['passed'] for x in checks),'registry_version':household['source_version'],'programme_version':programme['version'],'synthetic':True}
                status='eligible' if eligibility['eligible'] else 'not_eligible'
                self.put(c,batches,'id',dict(id='core-app-'+str(aid),programme_id=programme['id'],workflow_status='initiated',eligibility_status='complete',entitlement_status='not_started',instruction_status='not_started',details={'application':aid,'eligible':eligibility['eligible']}))
            elif action=='enroll' and app['status']=='eligible':
                if not eligibility or not eligibility['eligible']:raise DomainConflict('Eligibility evidence is required.')
                household=c.execute(select(entities).where(entities.c.reference==app['household_ref']).with_for_update()).mappings().one()
                if household['source_version']!=eligibility['registry_version'] or programme['version']!=eligibility['programme_version']:raise DomainConflict('Registry or programme rules changed. Reassess eligibility before enrollment.')
                if not all(x['passed'] for x in evaluate_rules(household['attributes'],programme['configuration'].get('rules',{}))):raise DomainConflict('Eligibility conditions no longer pass. Reassess before enrollment.')
                status='enrolled'
                c.execute(update(batches).where(batches.c.id=='core-app-'+str(aid)).values(workflow_status='approved_final_enrolment',entitlement_status='complete'))
            elif action=='reject' and app['status'] in ['pending_review','eligible']:status='rejected'
            else:raise DomainConflict('This action is unavailable in the current application state.')
            version=app['version']+1
            c.execute(update(applications).where(applications.c.id==aid).values(status=status,eligibility=eligibility,version=version,updated_at=now()))
            self.put(c,outbox,'key',dict(key='application:'+str(aid),kind='application',payload={'id':aid},status='pending',attempts=0,error=None,updated_at=now()))
            self.event(c,'application:'+str(aid)+':'+str(version),app['household_ref'],'application_'+action,actor,{'status':status,'eligibility':eligibility})
            return status

    def rows(self,table):
        with self.engine.connect() as c:return [dict(x) for x in c.execute(select(table)).mappings()]

    def mark_projection(self,key,error=None):
        with self.engine.begin() as c:
            c.execute(update(outbox).where(outbox.c.key==key).values(status='pending' if error else 'complete',attempts=outbox.c.attempts+1,error='Projection pending; retry scheduled' if error else None,updated_at=now()))
