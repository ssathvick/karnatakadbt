"""Own IAM data-policy persistence and filter-tree validation."""
import logging,uuid
from typing import Annotated,Any,Literal,Union
from pydantic import BaseModel,Field
from sqlalchemy import MetaData,Table,delete,func,select
from native_iam_business import NativeIamBusiness,IamBusinessError
class PolicyCondition(BaseModel):
    type:Literal['CONDITION']='CONDITION'
    field_id:str
    operator:Literal['eq','neq','in','nin','contains','ncontains','startsWith','endsWith','gt','gte','lt','lte','isNull']
    value:Any=None
    values:list[Any]|None=None
class PolicyGroup(BaseModel):
    type:Literal['GROUP']='GROUP'
    operator:Literal['AND','OR','NOT']
    children:list[Annotated[Union['PolicyGroup',PolicyCondition],Field(discriminator='type')]]=Field(default_factory=list)
PolicyGroup.model_rebuild()
class NativeIamPolicy(NativeIamBusiness):
    def __init__(self,engine,identity_admin=None):
        super().__init__(engine,identity_admin);self.policy_table=Table('data_policies',MetaData(),schema='public',autoload_with=engine)
    def policy_view(self,row):return {key:row[key] for key in ['policy_id','policy_mnemonic','policy_description','register_id','policy_target','policy_type','policy_filter_expression','application_id']}
    def get_policy(self,identifier):
        with self.engine.connect() as c:
            row=c.execute(select(self.policy_table).where(self.policy_table.c.policy_id==identifier)).mappings().first()
            if row is None:raise IamBusinessError('Data policy not found: '+str(identifier))
            return self.policy_view(row)
    def all_policies(self,application_id=None,policy_target=None,register_id=None):
        table=self.policy_table;query=select(table).order_by(table.c.policy_mnemonic,table.c.policy_target)
        for key,value in [('application_id',application_id),('policy_target',policy_target),('register_id',register_id)]:
            if value is not None:query=query.where(table.c[key]==value)
        with self.engine.connect() as c:
            rows=c.execute(query).mappings().all();return [self.policy_view(row) for row in rows],len(rows)
    def evaluate_policies(self,mnemonics):
        if not mnemonics:return []
        with self.engine.connect() as c:return [self.policy_view(row) for row in c.execute(select(self.policy_table).where(self.policy_table.c.policy_mnemonic.in_(mnemonics))).mappings()]
    def add_policy(self,data):
        expression=data['policy_filter_expression']
        if not isinstance(expression,dict):raise IamBusinessError('policy_filter_expression must be a JSON object')
        try:expression=(PolicyCondition if expression.get('type')=='CONDITION' else PolicyGroup).model_validate(expression).model_dump(mode='json')
        except ValueError:raise IamBusinessError('Invalid policy filter expression') from None
        target=data.get('policy_target','REGISTER_RECORD');register=data.get('register_id');application=data.get('application_id');mnemonic=data['policy_mnemonic']
        if target=='REGISTER_RECORD' and not register:raise IamBusinessError('register_id is required when policy_target is REGISTER_RECORD')
        if target in {'GEO','ATTRIBUTE'} and register:raise IamBusinessError('register_id must be null when policy_target is GEO or ATTRIBUTE')
        if application is not None and not mnemonic.startswith('DP_'):mnemonic='DP_'+mnemonic
        table=self.policy_table
        with self.transaction() as c:
            exists=c.execute(select(table).where(table.c.policy_mnemonic==mnemonic,table.c.policy_target==target,table.c.application_id.is_(None) if application is None else table.c.application_id==application,table.c.register_id.is_(None) if register is None else table.c.register_id==register)).first()
            if exists:raise IamBusinessError("Policy mnemonic '"+mnemonic+"' already exists for "+("register '"+register+"'" if register else 'global')+" target '"+target+"'")
            values={'policy_id':str(uuid.uuid4()),'policy_mnemonic':mnemonic,'policy_description':data.get('policy_description'),'register_id':register,'policy_target':target,'policy_type':data['policy_type'],'policy_filter_expression':expression,'application_id':application}
            c.execute(table.insert().values(**values))
            if application is not None:
                app=self.one(c,'application',id=application)
                if app:
                    self.bind_identity_entity('policy',values['policy_id'])
                    self.identity('create_role',mnemonic,app['application_mnemonic'],role_description=data.get('policy_description'))
            return self.policy_view(values)
    def remove_policy(self,identifier):
        table=self.policy_table
        with self.transaction() as c:
            row=c.execute(select(table).where(table.c.policy_id==identifier)).mappings().first()
            if row is None:raise IamBusinessError('Data policy not found: '+str(identifier))
            if row['application_id'] is not None:
                app=self.one(c,'application',id=row['application_id'])
                shared=c.execute(select(table.c.policy_id).where(table.c.application_id==row['application_id'],table.c.policy_mnemonic==row['policy_mnemonic'],table.c.policy_id!=identifier)).first()
                if app and not shared:
                    self.bind_identity_entity('policy',identifier)
                    self.identity('delete_role',row['policy_mnemonic'],app['application_mnemonic'])
            c.execute(delete(table).where(table.c.policy_id==identifier));return {'policy_id':identifier}
