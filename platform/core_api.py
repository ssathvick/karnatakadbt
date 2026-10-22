"""FastAPI entrypoint and documented, session-protected independent-domain API."""
import json,secrets,time
from decimal import Decimal
from fastapi import Depends,FastAPI,Header,HTTPException,Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field,ConfigDict
from sqlalchemy import select,func,text
from a2wsgi import WSGIMiddleware
from core_store import entities,programmes,applications,history,events,outbox

class ProgrammeCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=100)
    mnemonic:str=Field(min_length=1,max_length=30,pattern=r'^[A-Za-z0-9_]+$')
    amount:Decimal=Field(gt=0,le=1000000,max_digits=12,decimal_places=2,allow_inf_nan=False)
    max_income:Decimal=Field(ge=0,le=1000000000,max_digits=14,decimal_places=2,allow_inf_nan=False)
    min_members:int=Field(ge=1,le=8)
    rules:dict|None=None

class ApplicationDecision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_status:str=Field(min_length=1,max_length=40)

class ProgrammeUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=100)
    amount:Decimal=Field(gt=0,le=1000000,max_digits=12,decimal_places=2,allow_inf_nan=False)
    max_income:Decimal=Field(ge=0,le=1000000000,max_digits=14,decimal_places=2,allow_inf_nan=False)
    min_members:int=Field(ge=1,le=8)
    rules:dict|None=None
    status:str=Field(pattern=r'^(ACTIVE|PAUSED|CLOSED)$')
    version:int=Field(ge=1)

def create_app(r):
    api=FastAPI(title='KarnatakaDBT independent domain API',version='1.0.0',docs_url='/registration/api/v2/docs',openapi_url='/registration/api/v2/openapi.json',redoc_url=None)

    def principal(request:Request):
        token=request.cookies.get('KA-INTAKE' if hasattr(r,'CONFIG') else 'KDBT-DEMO','')
        session=r.one('SELECT * FROM sessions WHERE id=? AND expires>?',(token,int(time.time())))
        data=json.loads(session['data']) if session else {}
        if not data.get('user'):raise HTTPException(401,'Sign in to continue.')
        return data

    def staff(p=Depends(principal)):
        roles={x.replace('iqs-','kdbt-') for x in p['user'].get('roles',[])}
        if p.get('mode')!='staff' or not roles.intersection({'kdbt-registration-officer','kdbt-verification-officer','kdbt-intake-reviewer','kdbt-programme-supervisor'}):raise HTTPException(403,'Assigned staff access is required.')
        return p

    def supervisor(p=Depends(staff)):
        if p.get('role')!='supervisor' and not any(x.endswith('programme-supervisor') for x in p['user']['roles']):raise HTTPException(403,'Programme supervisor access is required.')
        return p

    @api.middleware('http')
    async def headers(request,call_next):
        response=await call_next(request)
        response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff';response.headers['X-Frame-Options']='DENY';response.headers['Referrer-Policy']='same-origin'
        return response

    def relay(request,path,body,csrf):
        if not csrf:raise HTTPException(403,'A session CSRF token is required.')
        client=r.app.test_client();name='KA-INTAKE' if hasattr(r,'CONFIG') else 'KDBT-DEMO'
        client.set_cookie(name,request.cookies.get(name,''),path='/registration' if hasattr(r,'CONFIG') else '/')
        if body.get('rules') is not None:body={**body,'rules':json.dumps(body['rules'])}
        else:body={k:v for k,v in body.items() if v is not None}
        response=client.post('/registration/api/next/'+path,data={**body,'csrf':csrf})
        return JSONResponse(response.json or {'error':'The operation could not complete.'},status_code=response.status_code)

    @api.get('/registration/api/v2/health')
    def health():
        with r.backend.store.engine.connect() as c:c.execute(text('SELECT 1'))
        return {'service':'KarnatakaDBT Core','status':'ok','backend':'FastAPI / SQLAlchemy / PostgreSQL' if r.backend.store.engine.dialect.name=='postgresql' else 'FastAPI / SQLAlchemy / test SQLite','odoo_required':False}

    @api.get('/registration/api/v2/registry')
    def registry(p=Depends(principal),limit:int=100,offset:int=0):
        if not 1<=limit<=200 or offset<0:raise HTTPException(400,'Use a bounded page size.')
        query=select(entities).where(entities.c.kind=='household').order_by(entities.c.reference)
        if p.get('mode')!='staff':query=query.where(entities.c.subject==p['user']['sub'])
        else:staff(p)
        with r.backend.store.engine.connect() as c:return {'records':[dict(row) for row in c.execute(query.limit(limit).offset(offset)).mappings()],'limit':limit,'offset':offset}

    @api.get('/registration/api/v2/programmes')
    def catalogue(p=Depends(principal)):
        query=select(programmes).order_by(programmes.c.id)
        if p.get('mode')!='staff':query=query.where(programmes.c.status=='ACTIVE')
        else:staff(p)
        with r.backend.store.engine.connect() as c:return {'programmes':[dict(row) for row in c.execute(query).mappings()],'currency_unit':'integer paise'}

    @api.post('/registration/api/v2/programmes')
    def create_programme(data:ProgrammeCreate,request:Request,p=Depends(supervisor),x_csrf_token:str|None=Header(default=None)):
        return relay(request,'programmes',data.model_dump(mode='json'),x_csrf_token)

    @api.get('/registration/api/v2/applications')
    def application_records(p=Depends(principal)):
        query=select(applications).order_by(applications.c.id)
        if p.get('mode')!='staff':query=query.where(applications.c.subject==p['user']['sub'])
        else:staff(p)
        with r.backend.store.engine.connect() as c:return {'applications':[dict(row) for row in c.execute(query.limit(200)).mappings()]}

    @api.patch('/registration/api/v2/programmes/{pid}')
    def edit_programme(pid:int,data:ProgrammeUpdate,request:Request,p=Depends(supervisor),x_csrf_token:str|None=Header(default=None)):
        return relay(request,'programmes/'+str(pid),data.model_dump(mode='json'),x_csrf_token)

    @api.post('/registration/api/v2/applications/{aid}/{action}')
    def decision(aid:int,action:str,data:ApplicationDecision,request:Request,p=Depends(staff),x_csrf_token:str|None=Header(default=None)):
        if action not in ['check','enroll','reject']:raise HTTPException(404,'Unknown application action.')
        return relay(request,'applications/'+str(aid)+'/'+action,data.model_dump(),x_csrf_token)

    @api.get('/registration/api/v2/migration')
    def migration(p=Depends(supervisor)):
        with r.backend.store.engine.connect() as c:
            groups=c.execute(select(history.c.source,history.c.entity,func.count()).group_by(history.c.source,history.c.entity)).all()
            pending=c.execute(select(func.count()).select_from(outbox).where(outbox.c.status!='complete')).scalar_one()
        return {'historical_records':[{'source':s,'entity':e,'count':n} for s,e,n in groups],'pending_projections':pending,'notice':'Preserved historical source records. They are not new Karnataka beneficiary approvals or live payment instructions.'}

    @api.get('/registration/api/v2/migration/{source}/{entity}')
    def migrated_records(source:str,entity:str,offset:int=0,limit:int=100,p=Depends(supervisor)):
        if not 1<=limit<=200 or offset<0:raise HTTPException(400,'Use a bounded page size.')
        with r.backend.store.engine.connect() as c:rows=c.execute(select(history).where(history.c.source==source,history.c.entity==entity).order_by(history.c.record_key).limit(limit).offset(offset)).mappings().all()
        return {'records':[dict(row) for row in rows],'offset':offset,'limit':limit,'historical':True}

    @api.get('/registration/api/v2/events')
    def audit(p=Depends(supervisor)):
        with r.backend.store.engine.connect() as c:return {'events':[dict(row) for row in c.execute(select(events).order_by(events.c.at.desc()).limit(100)).mappings()]}

    # The established knowledge, OIDC and simulation applications keep their
    # existing routes while the independent domain API owns the replacement.
    api.mount('/',WSGIMiddleware(r.app))
    return api

def native_app():
    import registration_app as r
    return create_app(r)
