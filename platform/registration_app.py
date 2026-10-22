"""KarnatakaDBT independent registry and programme backend."""
import os,json,sqlite3,secrets,time,uuid,hashlib,base64,threading,subprocess,datetime,logging,fcntl
from pathlib import Path
from urllib.parse import urlencode
import requests,jwt,psycopg2
import karnataka_geography
import knowledge_management
import local_ai
from psycopg2 import sql
from flask import Flask,request,redirect,render_template,abort,g

ROOT=Path(os.environ.get('IQS_REGISTRATION_ROOT','/runtime/registration'))
ROOT.mkdir(parents=True,exist_ok=True);CONFIG=json.loads((ROOT/'config.json').read_text())
BASE=CONFIG['base_url'];PREFIX='/registration'
class IntegrationLock:
 def __init__(self):self.local=threading.RLock();self.depth=0;self.fd=None
 def __enter__(self):
  self.local.acquire()
  if self.depth==0:self.fd=open(ROOT/'integration.lock','a');fcntl.flock(self.fd,fcntl.LOCK_EX)
  self.depth+=1
 def __exit__(self,*args):
  self.depth-=1
  if self.depth==0:fcntl.flock(self.fd,fcntl.LOCK_UN);self.fd.close()
  self.local.release()
LOCK=IntegrationLock()
app=Flask(__name__,template_folder=str(ROOT/'templates'),static_folder=str(ROOT/'static'),static_url_path=PREFIX+'/static')
app.config['MAX_CONTENT_LENGTH']=60000
logging.basicConfig(level=logging.INFO)
def db():
 c=sqlite3.connect(ROOT/'intake.sqlite',timeout=30);c.row_factory=sqlite3.Row;c.execute('PRAGMA journal_mode=WAL');return c
def execute(q,args=()):
 with db() as c:return c.execute(q,args).lastrowid
def rows(q,args=()):
 with db() as c:return [dict(r) for r in c.execute(q,args)]
def one(q,args=()):
 r=rows(q,args);return r[0] if r else None
with db() as c:
 c.executescript('''
 CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,data TEXT,expires INTEGER);
 CREATE TABLE IF NOT EXISTS profiles(sub TEXT PRIMARY KEY,ref TEXT UNIQUE,household_ref TEXT UNIQUE,data TEXT,status TEXT DEFAULT 'pending_review',sync_status TEXT DEFAULT 'not_started',error TEXT,portal_partner INTEGER,mapping TEXT,updated TEXT);
 CREATE TABLE IF NOT EXISTS programs(id INTEGER PRIMARY KEY,mnemonic TEXT UNIQUE,name TEXT,amount REAL,max_income REAL,min_members INTEGER,portal_id INTEGER,cycle_id INTEGER,benefit_id INTEGER,status TEXT DEFAULT 'ACTIVE');
 CREATE TABLE IF NOT EXISTS applications(id INTEGER PRIMARY KEY AUTOINCREMENT,sub TEXT,program INTEGER,status TEXT DEFAULT 'pending_review',portal_info INTEGER,portal_membership INTEGER,pbms_list INTEGER,error TEXT,created TEXT,UNIQUE(sub,program));
 CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,actor TEXT,action TEXT,reference TEXT,at TEXT);
 ''')
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
with db() as c:
 if 'last_editor' not in {row[1] for row in c.execute('PRAGMA table_info(profiles)')}:
  c.execute('ALTER TABLE profiles ADD COLUMN last_editor TEXT')
def audit(action,reference):execute('INSERT INTO audit(actor,action,reference,at) VALUES(?,?,?,?)',(g.user.get('sub','system') if hasattr(g,'user') else 'system',action,str(reference),stamp()))
def is_maker(profile,actor):
 return profile['sub']==actor or profile.get('last_editor')==actor or bool(one("SELECT id FROM audit WHERE actor=? AND reference IN (?,?) AND action IN ('registration_submitted','officer_corrected_and_resubmitted') LIMIT 1",(actor,profile['sub'],profile['household_ref'])))
def svc(name):
 raise RuntimeError('Legacy cluster discovery is unavailable in the local installation')

def pg(database,service='commons-postgresql'):
 aliases={'master_data':'kdbt_master','social_registry':'kdbt_registry_candidate_local'}
 allowed={'kdbt_core','kdbt_master','kdbt_registry_candidate_local'}
 target=aliases.get(database,database)
 if target not in allowed:raise ValueError('Use the native application database')
 values=json.loads(Path('/runtime/secrets.json').read_text())
 return psycopg2.connect(host='postgres',dbname=target,user='kdbt',password=values['postgres_password'],connect_timeout=10)

def upsert_pg(cur,table,data,key):
 columns=list(data);updates=[k for k in columns if k!=key]
 cur.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {}').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,columns)),sql.SQL(',').join(sql.Placeholder() for _ in columns),sql.Identifier(key),sql.SQL(',').join(sql.SQL('{}=EXCLUDED.{}').format(sql.Identifier(k),sql.Identifier(k)) for k in updates)),list(data.values()))
def issuer(mode):return CONFIG['keycloak']+'/realms/'+('staff' if mode=='staff' else 'beneficiary')
@app.before_request
def context():
 if request.path==PREFIX+'/api/analytics/context':return
 if request.path.endswith('/health'):return
 sid=request.cookies.get('KA-INTAKE');s=one('SELECT * FROM sessions WHERE id=? AND expires>?',(sid or '',int(time.time())))
 g.session=json.loads(s['data']) if s else {};g.sid=sid if s else secrets.token_urlsafe(32);g.user=g.session.get('user',{})
 g.session.setdefault('csrf',secrets.token_urlsafe(32));g.staff=g.session.get('mode')=='staff' and 'iqs-intake-reviewer' in g.user.get('roles',[])
 if request.method=='POST' and not secrets.compare_digest(request.form.get('csrf',''),g.session['csrf']):abort(403,'Session expired. Reload the page and try again.')
@app.after_request
def cookies(res):
 if hasattr(g,'session'):
  execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?)',(g.sid,json.dumps(g.session),int(time.time())+3600))
  res.set_cookie('KA-INTAKE',g.sid,max_age=3600,secure=True,httponly=True,samesite='Lax',path=PREFIX)
 res.headers['Cache-Control']='no-store';res.headers['X-Content-Type-Options']='nosniff';res.headers['X-Frame-Options']='DENY';res.headers['Referrer-Policy']='same-origin'
 return res
def require_user():
 if not g.user:abort(401,'Please sign in first.')
def require_staff():
 if not g.staff and not getattr(g,'workspace_verification_authorized',False):abort(403,'Staff reviewer access is required.')
def page(name,**kw):return render_template(name,user=g.user,staff=g.staff,csrf=g.session['csrf'],base=BASE,prefix=PREFIX,**kw)
@app.get(PREFIX+'/health')
def health():
 return {'status':'ok','service':'KarnatakaDBT independent domain backend','odoo_required':False}
@app.get(PREFIX+'/login')
def login():
 mode='staff' if request.args.get('mode')=='staff' else 'beneficiary';state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48);nonce=secrets.token_urlsafe(32)
 g.session['login']={'mode':mode,'state':state,'verifier':verifier,'nonce':nonce,'at':int(time.time()),'workspace':request.args.get('workspace')=='1','geography':request.args.get('geography')=='1','knowledge':request.args.get('knowledge')=='1','analytics':request.args.get('analytics')=='1','simulation':request.args.get('simulation')=='1','ai':request.args.get('ai')=='1','ai_module':request.args.get('module','platform')[:80],'ai_stage':request.args.get('stage','')[:160]}
 g.session['login']['register_lab']=request.args.get('register_lab')=='1'
 g.session['login']['register_lab']=request.args.get('register_lab')=='1'
 g.session['login']['register_lab']=request.args.get('register_lab')=='1'
 g.session['login']['register_lab']=request.args.get('register_lab')=='1'
 g.session['login']['grievances']=request.args.get('grievances')=='1'
 g.session['login']['learning']=request.args.get('learning')=='1'
 client=CONFIG['clients'][mode];params={'client_id':client['id'],'response_type':'code','scope':'openid profile email','redirect_uri':BASE+PREFIX+'/callback','state':state,'nonce':nonce,'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='),'code_challenge_method':'S256'}
 endpoint='registrations' if request.args.get('signup')=='1' and mode=='beneficiary' else 'auth'
 return redirect(issuer(mode)+'/protocol/openid-connect/'+endpoint+'?'+urlencode(params))
@app.get(PREFIX+'/callback')
def callback():
 flow=g.session.pop('login',{})
 if not flow or not secrets.compare_digest(flow['state'],request.args.get('state','')) or time.time()-flow['at']>600:abort(400,'Invalid or expired sign-in request.')
 if request.args.get('error'):abort(400,'Sign-in was cancelled. Return to registration and try again.')
 client=CONFIG['clients'][flow['mode']];iss=issuer(flow['mode'])
 r=requests.post(iss+'/protocol/openid-connect/token',data={'grant_type':'authorization_code','code':request.args.get('code'),'client_id':client['id'],'client_secret':client['secret'],'redirect_uri':BASE+PREFIX+'/callback','code_verifier':flow['verifier']},timeout=20);r.raise_for_status()
 tokens=r.json();jwks=requests.get(iss+'/protocol/openid-connect/certs',timeout=20);jwks.raise_for_status()
 kid=jwt.get_unverified_header(tokens['id_token']).get('kid');key=jwt.PyJWK.from_dict(next(k for k in jwks.json()['keys'] if k['kid']==kid and k.get('use')=='sig')).key
 claims=jwt.decode(tokens['id_token'],key,algorithms=['RS256'],audience=client['id'],issuer=iss)
 if not secrets.compare_digest(claims.get('nonce',''),flow['nonce']):abort(400,'Invalid login nonce.')
 access=jwt.decode(tokens['access_token'],key,algorithms=['RS256'],issuer=iss,options={'verify_aud':False})
 g.session={'csrf':secrets.token_urlsafe(32),'mode':flow['mode'],'user':{'sub':claims['sub'],'name':claims.get('name',claims.get('preferred_username','')),'email':claims.get('email',''),'roles':access.get('realm_access',{}).get('roles',[])}}
 old=g.sid;g.sid=secrets.token_urlsafe(32);execute('DELETE FROM sessions WHERE id=?',(old,))
 if flow.get('learning'):return redirect(PREFIX+'/learning')
 if flow.get('register_lab'):return redirect(PREFIX+'/register-lab')
 if flow.get('register_lab'):return redirect(PREFIX+'/register-lab')
 if flow.get('register_lab'):return redirect(PREFIX+'/register-lab')
 if flow.get('register_lab'):return redirect(PREFIX+'/register-lab')
 if flow.get('ai'):return redirect(PREFIX+'/ai?'+urlencode({'module':flow.get('ai_module','platform'),'stage':flow.get('ai_stage','')}))
 return redirect(PREFIX+'/simulation' if flow.get('simulation') else PREFIX+'/analytics' if flow.get('analytics') else PREFIX+'/knowledge/admin' if flow.get('knowledge') else PREFIX+'/geography' if flow.get('geography') else PREFIX+'/workspace' if flow.get('workspace') else (PREFIX+'/staff' if flow['mode']=='staff' else PREFIX+'/'))
@app.post(PREFIX+'/logout')
def logout():g.session={};return redirect(PREFIX+'/')
@app.get(PREFIX+'/')
def home():
 p=one('SELECT * FROM profiles WHERE sub=?',(g.user.get('sub',''),));programs=rows("SELECT * FROM programs WHERE status='ACTIVE'")
 apps=rows('SELECT a.*,p.name FROM applications a JOIN programs p ON p.id=a.program WHERE a.sub=?',(g.user.get('sub',''),))
 return page('home.html',profile=p,programs=programs,applications=apps)
@app.get(PREFIX+'/profile')
def profile_form():
 require_user()
 if g.session['mode']!='beneficiary':abort(403)
 p=one('SELECT * FROM profiles WHERE sub=?',(g.user['sub'],))
 data=json.loads(p['data']) if p else {}
 with pg('master_data') as c:
  with c.cursor() as cur:cur.execute("SELECT level_value_id,level_value_mnemonic FROM g2p_geo_level_values WHERE level_id='district' ORDER BY level_value_mnemonic");states=cur.fetchall()
 return page('profile.html',profile=p,data=data,states=states,geocatalogue=karnataka_geography.CATALOGUE)
def clean(value,length=100):
 value=(value or '').strip()
 if len(value)>length:raise ValueError('A field exceeds its maximum length.')
 return value
@app.post(PREFIX+'/profile')
def profile_save():
 require_user()
 if g.session['mode']!='beneficiary':abort(403)
 with LOCK:
  p=one('SELECT * FROM profiles WHERE sub=?',(g.user['sub'],))
  if p and p['status']=='approved':abort(409,'This approved profile is locked. Contact the reviewer for corrections.')
  try:
   members=[]
   for i in range(8):
    given=clean(request.form.get(f'given_{i}'));family=clean(request.form.get(f'family_{i}'))
    if not given and not family:continue
    if not given or not family:raise ValueError('Each member needs a given and family name.')
    birth=datetime.date.fromisoformat(request.form.get(f'birth_{i}',''))
    if birth>datetime.date.today() or birth.year<1900:raise ValueError('Check the date of birth.')
    gender=request.form.get(f'gender_{i}')
    if gender not in ['Female','Male','Other']:raise ValueError('Select a gender for each member.')
    members.append({'given':given,'family':family,'birth_date':str(birth),'gender':gender,'ref':'KA-REG-I-'+uuid.uuid5(uuid.NAMESPACE_URL,g.user['sub']+'/member/'+str(i)).hex[:16]})
   if not members or not request.form.get('synthetic'):raise ValueError('Add the applicant and confirm synthetic data use.')
   state=clean(request.form.get('state'));income=float(request.form.get('income','0'));__import__('core_store').minor(request.form.get('income','0'))
   if not 0<=income<=1000000000:raise ValueError('Income must be a non-negative monthly amount.')
   with pg('master_data') as c:
    with c.cursor() as cur:cur.execute('SELECT level_value_mnemonic FROM g2p_geo_level_values WHERE level_value_id=%s',(state,));state_row=cur.fetchone()
   if not state_row:raise ValueError('Choose a valid state or FCT.')
   data={'members':members,'state':state,'state_name':state_row[0],'community':clean(request.form.get('community')),'household_name':clean(request.form.get('household_name')),'monthly_income':income,'email':g.user.get('email',''),'synthetic':True}
   if not data['household_name']:raise ValueError('Enter a household name.')
   data['geography']=karnataka_geography.capture(request.form,data)
  except (ValueError,TypeError) as e:return page('message.html',title='Please check the form',message=str(e),back=PREFIX+'/profile'),400
  ref=members[0]['ref'];hh='KA-REG-HH-'+uuid.uuid5(uuid.NAMESPACE_URL,g.user['sub']+'/household').hex[:16]
  execute("INSERT INTO profiles(sub,ref,household_ref,data,status,updated) VALUES(?,?,?,?,'pending_review',?) ON CONFLICT(sub) DO UPDATE SET data=excluded.data,status='pending_review',error=NULL,updated=excluded.updated",(g.user['sub'],ref,hh,json.dumps(data),stamp()));audit('registration_submitted',hh)
 return redirect(PREFIX+'/')
def sync_profile(sub):
 return backend.sync_profile(sub)
def create_program(mnemonic,name,amount,max_income,min_members):
 return backend.create_programme(mnemonic,name,amount,max_income,min_members)
def update_rules(pid):
 return backend.refresh_rules(pid)
def link_portal_application(a):
 return backend.link_application(a)
def start_eligibility(a):
 return backend.decide_application(a['id'],'check')
@app.post(PREFIX+'/apply/<int:pid>')
def apply_program(pid):
 return backend.apply_form(pid)
@app.get(PREFIX+'/staff')
def staff_home():
 require_staff();return page('staff.html',profiles=rows('SELECT * FROM profiles ORDER BY updated DESC'),applications=rows('SELECT a.*,p.name,r.household_ref FROM applications a JOIN programs p ON p.id=a.program JOIN profiles r ON r.sub=a.sub ORDER BY a.id DESC'),programs=rows('SELECT * FROM programs'),events=rows('SELECT * FROM audit ORDER BY id DESC LIMIT 20'))
@app.get(PREFIX+'/staff/profile/<sub>')
def staff_profile(sub):
 require_staff();p=one('SELECT * FROM profiles WHERE sub=?',(sub,))
 if not p:abort(404)
 return page('review.html',profile=p,data=json.loads(p['data']))
@app.post(PREFIX+'/staff/profile/<sub>/<action>')
def staff_profile_decision(sub,action):
 require_staff()
 if action not in ['approve','reject','retry']:abort(404)
 with LOCK:
  p=one('SELECT * FROM profiles WHERE sub=?',(sub,))
  if not p:abort(404)
  if action=='reject':
   if p['status']!='pending_review':abort(409,'This registration is no longer awaiting review.')
   if is_maker(p,g.user['sub']):abort(403,'A different reviewer must decide a record you created or corrected.')
   if p['status']=='approved':abort(409,'Approved records cannot be rejected retrospectively.')
   reason=clean(request.form.get('reason'),500)
   if len(reason)<10:abort(400,'Give a clear correction reason of at least 10 characters.')
   execute("UPDATE profiles SET status='rejected',error=?,updated=? WHERE sub=?",(reason,stamp(),sub))
  else:
   if action=='retry' and p['status']!='approved':abort(409)
   if action=='approve':
    if p['status']!='pending_review':abort(409,'This record is no longer awaiting review.')
    if is_maker(p,g.user['sub']):abort(403,'A different reviewer must decide a record you created or corrected.')
   execute("UPDATE profiles SET status='approved',sync_status='pending',error=NULL,updated=? WHERE sub=?",(stamp(),sub))
   try:sync_profile(sub)
   except Exception:logging.exception('Profile synchronization failed');execute("UPDATE profiles SET sync_status='pending',error='A backend is unavailable. The saved registration will retry.' WHERE sub=?",(sub,))
  audit('registration_'+action,sub)
 return redirect(PREFIX+'/staff')
@app.post(PREFIX+'/staff/program')
def staff_program_create():
 return backend.programme_form()
@app.post(PREFIX+'/staff/application/<int:aid>/<action>')
def staff_application_decision(aid,action):
 return backend.decision_form(aid,action)
def reconcile():
 return backend.reconcile()
@app.errorhandler(Exception)
def error(e):
 from werkzeug.exceptions import HTTPException
 if isinstance(e,HTTPException):
  if request.path.startswith(PREFIX+'/api/'):return {'error':e.description},e.code
  return page('message.html',title='Action needs attention',message=e.description,back=PREFIX+'/'),e.code
 logging.exception('Integration request failed')
 if request.path.startswith(PREFIX+'/api/'):return {'error':'Service temporarily unavailable. Refresh before trying again.'},503
 return page('message.html',title='Service temporarily unavailable',message='Your saved records are retained. Try again shortly; staff can inspect integration logs.',back=PREFIX+'/'),503
import domain_runtime
backend=domain_runtime.bind(os.sys.modules[__name__])
import native_addons
native_addons.install(os.sys.modules[__name__])
import registration_workspaces
registration_workspaces.install(os.sys.modules[__name__])
karnataka_geography.install(os.sys.modules[__name__])
knowledge_management.install(os.sys.modules[__name__])
local_ai.install(os.sys.modules[__name__])
import platform_analytics
platform_analytics.install(os.sys.modules[__name__])
import partner_simulation
partner_simulation.install(os.sys.modules[__name__])
import services
services.install(os.sys.modules[__name__])
import runtime_ai
runtime_ai.configure(local_ai)
import external_registers
external_registers.install(os.sys.modules[__name__])
import analytics_completion
analytics_completion.install(os.sys.modules[__name__])
import next_frontend
next_frontend.install(__import__('sys').modules[__name__])
if __name__=='__main__':
 if '--reconcile' in os.sys.argv:reconcile()
 else:app.run(host='127.0.0.1',port=18081)
