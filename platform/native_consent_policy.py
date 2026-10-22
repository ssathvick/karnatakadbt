"""Independent consent policy-binding engine on the migration-preserved schema.

Scope: staff policy bindings, versioning, decision reads and signed approval
callbacks. Consent origination, subject APIs and signature validation are separate
dependencies and are deliberately not claimed as replaced by this module.
"""
import hashlib,hmac,json,re,time,uuid
from contextlib import contextmanager
from datetime import datetime,timezone
from sqlalchemy import MetaData,Table,select,text

class ConsentPolicyError(Exception):
    def __init__(self,status,message):self.status,self.message=status,message;super().__init__(message)
def now():return datetime.now(timezone.utc)
def duration(value):
    match=re.fullmatch(r'P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?',value.strip())
    if not match:raise ValueError('Invalid policy duration')
    numbers=[int(v or 0) for v in match.groups()]
    return sum(v*unit for v,unit in zip(numbers,[365*86400,30*86400,7*86400,86400,3600,60,1]))
class NativeConsentPolicy:
    def __init__(self,engine,*,approval_enabled=False,callback_secret=None,webhook_max_skew=300,submission_outbox=None):
        if not isinstance(webhook_max_skew,int) or webhook_max_skew<0:raise ValueError('Invalid callback skew')
        self.engine=engine;self.approval_enabled=approval_enabled;self.callback_secret=callback_secret;self.max_skew=webhook_max_skew
        self.submission_outbox=submission_outbox
        metadata=MetaData();self.tables={name:Table(name,metadata,schema='public',autoload_with=engine) for name in ['partners','partner_policies','cm_awe_processed_events','decision_logs']}
    @contextmanager
    def transaction(self):
        with self.engine.begin() as c:
            c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('karnatakadbt-native-consent-policy',0))"));yield c
    def one(self,c,kind,**filters):
        table=self.tables[kind];query=select(table)
        for field,value in filters.items():query=query.where(table.c[field]==value)
        row=c.execute(query).mappings().first();return dict(row) if row else None
    def put(self,c,kind,values):
        table=self.tables[kind];values={'id':str(uuid.uuid4()),'created_at':now(),'updated_at':now(),**values};c.execute(table.insert().values(**values));return self.one(c,kind,id=values['id'])
    def update(self,c,kind,identifier,values):
        table=self.tables[kind];c.execute(table.update().where(table.c.id==identifier).values(**values,updated_at=now()));return self.one(c,kind,id=identifier)
    def binding(self,identifier):
        with self.engine.connect() as c:return self.one(c,'partners',id=identifier)
    def create_binding(self,data):
        with self.transaction() as c:return self.put(c,'partners',{'name':data.get('name'),'audience':data['audience'],'controller_id':data['controller_id'],'partner_mgmt_id':data.get('partner_mgmt_id'),'status':'active'})
    def update_binding(self,identifier,data):
        with self.transaction() as c:
            if not self.one(c,'partners',id=identifier):return None
            return self.update(c,'partners',identifier,{k:v for k,v in data.items() if k in {'name','status','partner_mgmt_id'} and v is not None})
    def bindings(self,controller_id=None,status=None):
        table=self.tables['partners'];query=select(table).order_by(table.c.created_at.desc())
        if controller_id:query=query.where(table.c.controller_id==controller_id)
        if status:query=query.where(table.c.status==status)
        with self.engine.connect() as c:return [dict(row) for row in c.execute(query).mappings()]
    @staticmethod
    def widened(data,active):
        if active is None:return True
        for field in ['allowed_data_scopes','allowed_purposes','allowed_subject_id_types','allowed_signing_algs']:
            if set(data.get(field) or [])-set(active.get(field) or []):return True
        for field in ['max_validity_duration','data_life']:
            new,old=data.get(field),active.get(field)
            if new==old or old is None:continue
            if new is None:return True
            try:
                if duration(new)>duration(old):return True
            except (ValueError,TypeError):return True
        return False
    def policies_in(self,c,identifier):
        table=self.tables['partner_policies'];return [dict(row) for row in c.execute(select(table).where(table.c.partner_id==identifier).order_by(table.c.version.desc())).mappings()]
    def policies(self,identifier):
        with self.engine.connect() as c:return self.policies_in(c,identifier) if self.one(c,'partners',id=identifier) else None
    def policy(self,identifier,version=None):
        with self.engine.connect() as c:
            return next((row for row in self.policies_in(c,identifier) if (row['version']==version if version is not None else row['status']=='active')),None)
    def upsert_policy(self,identifier,data):
        with self.transaction() as c:
            if not self.one(c,'partners',id=identifier):return None
            previous=self.policies_in(c,identifier);active=next((row for row in previous if row['status']=='active'),None)
            pending=self.approval_enabled and self.widened(data,active)
            if active and not pending:self.update(c,'partner_policies',active['id'],{'status':'superseded'})
            policy=self.put(c,'partner_policies',{**data,'partner_id':identifier,'version':previous[0]['version']+1 if previous else 1,'status':'pending' if pending else 'active','effective_from':None if pending else now()})
            if pending and self.submission_outbox:self.submission_outbox.enqueue(c,policy,self.one(c,'partners',id=identifier))
            return policy
    def set_request(self,policy_id,request_id):
        with self.transaction() as c:
            if self.one(c,'partner_policies',id=policy_id):self.update(c,'partner_policies',policy_id,{'awe_request_id':request_id})
    def apply_in(self,c,request_id,artifact_id,approved):
        policy=self.one(c,'partner_policies',awe_request_id=request_id) if request_id else None
        if policy is None and artifact_id:policy=self.one(c,'partner_policies',id=artifact_id)
        if policy is None:return False
        if policy['status']!='pending':return True
        if approved:
            for previous in self.policies_in(c,policy['partner_id']):
                if previous['status']=='active':self.update(c,'partner_policies',previous['id'],{'status':'superseded'})
        self.update(c,'partner_policies',policy['id'],{'status':'active' if approved else 'rejected',**({'effective_from':now()} if approved else {})});return True
    def apply_decision(self,request_id,artifact_id,approved):
        with self.transaction() as c:return self.apply_in(c,request_id,artifact_id,approved)
    def decisions(self,partner_id=None,decision=None,limit=50):
        table=self.tables['decision_logs'];query=select(table).order_by(table.c.created_at.desc()).limit(limit)
        if partner_id:query=query.where(table.c.partner_id==partner_id)
        if decision:query=query.where(table.c.decision==decision)
        with self.engine.connect() as c:return [dict(row) for row in c.execute(query).mappings()]
    def verify_signature(self,raw,timestamp,signature):
        if not self.callback_secret:raise ConsentPolicyError(500,'AWE callback secret is not configured')
        if not timestamp or not signature:raise ConsentPolicyError(401,'Missing signature headers')
        try:stamp=int(timestamp)
        except (ValueError,TypeError):raise ConsentPolicyError(401,'Invalid timestamp header') from None
        if abs(time.time()-stamp)>self.max_skew:raise ConsentPolicyError(401,'Signature timestamp outside allowed skew')
        secret=self.callback_secret.encode() if isinstance(self.callback_secret,str) else self.callback_secret
        expected='sha256='+hmac.new(secret,str(stamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,signature):raise ConsentPolicyError(401,'Signature verification failed')
    def process_event(self,event_id,event):
        if not event_id:raise ConsentPolicyError(401,'Missing event id')
        with self.transaction() as c:
            if self.one(c,'cm_awe_processed_events',event_id=event_id):return 'duplicate'
            kind=event.get('event_type','');request=event.get('request_id','');artifact=event.get('artifact_id','')
            if kind in {'request_approved','request_rejected','request_cancelled'}:
                if not self.apply_in(c,request,artifact,kind=='request_approved'):raise ConsentPolicyError(422,'No policy for AWE request '+str(request or artifact))
                outcome='approved' if kind=='request_approved' else 'rejected'
            else:outcome='ignored'
            self.put(c,'cm_awe_processed_events',{'event_id':event_id,'event_type':kind,'request_id':request,'processed_at':now()})
            return outcome
