"""Own IAM application/access/provider business engine; identity stays separate.

Database schema is retained for reversible migration. Client/role changes require
an explicit identity-admin adapter; missing adapters fail closed. Secrets are
stored only in provider persistence and never returned by administrative views.
"""
from contextlib import contextmanager
from datetime import datetime,timezone
from sqlalchemy import MetaData,Table,delete,func,or_,select,text
class IamBusinessError(Exception):
    def __init__(self,message,missing=False):self.message=message;self.code='G2P-REQ-404' if missing else 'G2P-REQ-400';super().__init__(message)
def now():return datetime.now(timezone.utc).replace(tzinfo=None)
class NativeIamBusiness:
    def __init__(self,engine,identity_admin=None):
        self.engine=engine;self.identity_admin=identity_admin;metadata=MetaData()
        names={'application':'staff_portal_applications','role':'staff_roles','permission':'staff_application_permissions','mapping':'staff_role_permissions','provider':'login_providers'}
        self.tables={kind:Table(name,metadata,schema='public',autoload_with=engine) for kind,name in names.items()}
    @contextmanager
    def transaction(self):
        try:
            with self.engine.begin() as c:
                c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('karnatakadbt-native-iam-business',0))"));yield c
        finally:
            reconcile=getattr(self.identity_admin,'reconcile',None)
            if reconcile:reconcile()
    def bind_identity_entity(self,kind,identifier):
        bind=getattr(self.identity_admin,'bind_business_entity',None)
        if bind:bind(kind,identifier)
    def identity(self,operation,*args,**kwargs):
        if self.identity_admin is None:raise IamBusinessError('Identity administration adapter is required')
        try:return getattr(self.identity_admin,operation)(*args,**kwargs)
        except Exception:raise IamBusinessError('Identity administration operation failed') from None
    def one(self,c,kind,**filters):
        table=self.tables[kind];query=select(table)
        for key,value in filters.items():query=query.where(table.c[key]==value)
        row=c.execute(query).mappings().first();return dict(row) if row else None
    def required(self,c,kind,identifier,label):
        row=self.one(c,kind,id=identifier)
        if row is None:raise IamBusinessError(label+' not found',True)
        return row
    def put(self,c,kind,data):
        table=self.tables[kind];return dict(c.execute(table.insert().values(**data,created_at=now(),updated_at=now()).returning(table)).mappings().one())
    def update(self,c,kind,identifier,data):
        table=self.tables[kind]
        if data:c.execute(table.update().where(table.c.id==identifier).values(**data,updated_at=now()))
        return self.one(c,kind,id=identifier)
    def view(self,kind,row):
        if row is None:return None
        result=dict(row)
        if kind=='provider':
            result['has_client_secret']=bool(result.pop('client_secret',None));result['has_client_private_key']=bool(result.pop('client_private_key',None))
        for key,value in result.items():
            if isinstance(value,datetime):result[key]=value.isoformat()
        return result
    def create_application(self,data):
        name=data['application_mnemonic'].strip()
        if not name:raise IamBusinessError('application_mnemonic is required')
        with self.transaction() as c:
            if self.one(c,'application',application_mnemonic=name):raise IamBusinessError("Application '"+name+"' already exists")
            row=self.put(c,'application',{key:data.get(key) for key in ['application_description','application_url','api_url','icon_base64','order','width']}|{'application_mnemonic':name,'active':True,'is_self_registered':False})
            self.bind_identity_entity('application',row['id'])
            _,existed=self.identity('create_client',name,description=data.get('application_description'))
            if existed:raise IamBusinessError("Failed to create Keycloak client: Application '"+name+"' already exists in Keycloak")
            return self.view('application',row)
    def update_application(self,data):
        with self.transaction() as c:
            row=self.required(c,'application',data['id'],'Application')
            if row['is_self_registered']:raise IamBusinessError('Self-registered applications cannot be edited from the staff UI')
            values={key:data[key] for key in ['application_description','application_url','api_url','icon_base64','order','width'] if data.get(key) is not None}
            return self.view('application',self.update(c,'application',data['id'],values))
    def delete_application(self,data):
        with self.transaction() as c:
            row=self.required(c,'application',data['id'],'Application')
            if row['is_self_registered']:raise IamBusinessError('Self-registered applications cannot be deleted from the staff UI')
            self.bind_identity_entity('application',row['id'])
            self.identity('delete_client',row['application_mnemonic'])
            role,permission,mapping=self.tables['role'],self.tables['permission'],self.tables['mapping']
            roles=select(role.c.id).where(role.c.application_id==data['id']);permissions=select(permission.c.id).where(permission.c.application_id==data['id'])
            c.execute(delete(mapping).where(or_(mapping.c.role_id.in_(roles),mapping.c.permission_id.in_(permissions))))
            c.execute(delete(role).where(role.c.application_id==data['id']));c.execute(delete(permission).where(permission.c.application_id==data['id']));c.execute(delete(self.tables['application']).where(self.tables['application'].c.id==data['id']))
            return self.view('application',row)
    def create_access(self,kind,data):
        field=kind+'_mnemonic';description=kind+'_description';name=data[field].strip()
        if not name:raise IamBusinessError(field+' is required')
        with self.transaction() as c:
            application=self.required(c,'application',data['application_id'],'Application')
            if self.one(c,kind,application_id=data['application_id'],**{field:name}):raise IamBusinessError(kind.capitalize()+" '"+name+"' already exists")
            row=self.put(c,kind,{'application_id':data['application_id'],field:name,description:data.get(description) if kind=='role' else data.get(description) or name,'active':True})
            if kind=='role':
                self.bind_identity_entity('role',row['id'])
                _,existed=self.identity('create_role',name,application['application_mnemonic'],role_description=data.get(description))
                if existed:raise IamBusinessError("Failed to sync role to Keycloak: Role '"+name+"' already exists in Keycloak")
            return self.view(kind,row)
    def delete_access(self,kind,data):
        with self.transaction() as c:
            app=self.required(c,'application',data['application_id'],'Application');row=self.one(c,kind,id=data['id'])
            if not row or row['application_id']!=data['application_id']:raise IamBusinessError(kind.capitalize()+' not found',True)
            if kind=='role':
                self.bind_identity_entity('role',row['id'])
                self.identity('delete_role',row['role_mnemonic'],app['application_mnemonic'])
            mapping=self.tables['mapping'];c.execute(delete(mapping).where(mapping.c[kind+'_id']==data['id']));table=self.tables[kind];c.execute(delete(table).where(table.c.id==data['id']));return self.view(kind,row)
    def mapping_view(self,c,row):
        role=self.one(c,'role',id=row['role_id']);permission=self.one(c,'permission',id=row['permission_id'])
        return self.view('mapping',{**row,'role_mnemonic':role['role_mnemonic'] if role else None,'permission_mnemonic':permission['permission_mnemonic'] if permission else None})
    def create_mapping(self,data):
        with self.transaction() as c:
            self.required(c,'application',data['application_id'],'Application')
            for kind in ['role','permission']:
                row=self.one(c,kind,id=data[kind+'_id'])
                if not row or row['application_id']!=data['application_id']:raise IamBusinessError(kind+'_id does not belong to this application')
            if self.one(c,'mapping',role_id=data['role_id'],permission_id=data['permission_id']):raise IamBusinessError('Mapping already exists')
            return self.mapping_view(c,self.put(c,'mapping',{'role_id':data['role_id'],'permission_id':data['permission_id'],'active':True}))
    def delete_mapping(self,data):
        with self.transaction() as c:
            self.required(c,'application',data['application_id'],'Application');row=self.one(c,'mapping',id=data['id']);role=self.one(c,'role',id=row['role_id']) if row else None
            if not row or not role or role['application_id']!=data['application_id']:raise IamBusinessError('Mapping not found',True)
            result=self.mapping_view(c,row);table=self.tables['mapping'];c.execute(delete(table).where(table.c.id==data['id']));return result
    def page(self,kind,data=None,page=1,page_size=20):
        data=data or {};table=self.tables[kind];query=select(table)
        with self.engine.connect() as c:
            if kind in {'role','permission','mapping'}:
                self.required(c,'application',data['application_id'],'Application')
                if kind=='mapping':
                    role=self.tables['role'];query=query.where(table.c.role_id.in_(select(role.c.id).where(role.c.application_id==data['application_id'])))
                    for field in ['role_id','permission_id']:
                        if data.get(field) is not None:query=query.where(table.c[field]==data[field])
                else:
                    query=query.where(table.c.application_id==data['application_id'])
                    if kind=='role':query=query.where(~table.c.role_mnemonic.like('DP_%'))
            total=c.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            query=query.order_by(table.c.created_at.desc().nullslast(),table.c.id.desc()) if kind=='application' else query.order_by(table.c.id.desc())
            rows=c.execute(query.offset((page-1)*page_size).limit(page_size)).mappings()
            return [self.mapping_view(c,dict(row)) if kind=='mapping' else self.view(kind,dict(row)) for row in rows],total
    def get(self,kind,identifier):
        with self.engine.connect() as c:return self.view(kind,self.required(c,kind,identifier,'Application' if kind=='application' else 'Login provider'))
    def create_provider(self,data):
        for field in ['provider_name','client_id','issuer','oauth_callback_url']:
            if not data.get(field,'').strip():raise IamBusinessError(field+' is required')
        fields=['provider_name','description','icon_base64','client_id','client_secret','client_private_key','token_endpoint_auth_method','issuer','authorization_endpoint','token_endpoint','userinfo_endpoint','server_metadata_url','jwks_uri','adapter_name','scope','enable_pkce','extra_authorize_params','jwt_assertion_aud','audiences','oauth_callback_url','default_redirect_uri']
        values={key:data.get(key) for key in fields}
        for field in ['provider_name','client_id','issuer','oauth_callback_url']:values[field]=values[field].strip()
        values['client_private_key']=values['client_private_key'].encode() if values['client_private_key'] else None
        with self.transaction() as c:return self.view('provider',self.put(c,'provider',{**values,'active':True}))
    def update_provider(self,data):
        with self.transaction() as c:
            self.required(c,'provider',data['id'],'Login provider');allowed=set(self.tables['provider'].c.keys())-{'id','active','created_at','updated_at','client_secret','client_private_key','keymanager_app_id','keymanager_ref_id'}
            values={key:value for key,value in data.items() if key in allowed and value is not None}
            if data.get('client_secret'):values['client_secret']=data['client_secret']
            if data.get('client_private_key'):values['client_private_key']=data['client_private_key'].encode()
            return self.view('provider',self.update(c,'provider',data['id'],values))
    def delete_provider(self,identifier):
        with self.transaction() as c:
            row=self.required(c,'provider',identifier,'Login provider');table=self.tables['provider'];c.execute(delete(table).where(table.c.id==identifier));return self.view('provider',row)
    def login_options(self):
        table=self.tables['provider']
        with self.engine.connect() as c:
            rows=c.execute(select(table).where(table.c.active.is_(True)).order_by(table.c.id.asc())).mappings()
            return {'loginProviders':[{'id':row['id'],'name':row['provider_name'],'displayName':row['description'] or row['provider_name'],'displayIconUrl':row['icon_base64'] or ''} for row in rows]}
