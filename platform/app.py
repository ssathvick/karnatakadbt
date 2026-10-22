"""Isolated KarnatakaDBT synthetic platform; inherited workflow modules run locally."""
import os,json,sqlite3,secrets,time,uuid,threading,datetime,math,sys,csv,io
from pathlib import Path
from flask import Flask,request,redirect,render_template,abort,g,send_from_directory
from werkzeug.exceptions import HTTPException
BASE_DIR=Path(__file__).resolve().parent
ROOT=Path(os.environ.get('KDBT_DATA_DIR',str(BASE_DIR.parent/'data')))
ROOT.mkdir(parents=True,exist_ok=True)
PREFIX='/registration';BASE='';LOCK=threading.RLock()
FULL_NAME='KarnatakaDBT Direct Benefit Transfer Fully AI Driven Automated Platform'
app=Flask(__name__,template_folder=str(BASE_DIR/'templates'),static_folder=str(BASE_DIR/'static'),static_url_path=PREFIX+'/static')
app.config['MAX_CONTENT_LENGTH']=100000
@app.before_request
def public_demo_gate():
 host=request.host.split(':',1)[0].lower()
 if host in ('127.0.0.1','localhost','[::1]'):return
 password=os.environ.get('KDBT_DEMO_ACCESS_PASSWORD','')
 if not password:return 'KarnatakaDBT public demo access has not been configured.',503
 auth=request.authorization
 if not auth or auth.username!='demo' or not secrets.compare_digest(auth.password or '',password):
  return 'KarnatakaDBT demo sign-in required.',401,{'WWW-Authenticate':'Basic realm="KarnatakaDBT demonstration"'}
CATALOGUE=json.loads((BASE_DIR/'karnataka-geography.json').read_text(encoding='utf-8'))
DISTRICTS={d['id']:d for d in CATALOGUE['districts']}
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def db():
 c=sqlite3.connect(ROOT/'karnataka-dbt.sqlite',timeout=30);c.row_factory=sqlite3.Row;c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA foreign_keys=ON');return c
def execute(q,args=()):
 with db() as c:return c.execute(q,args).lastrowid
def rows(q,args=()):
 with db() as c:return [dict(x) for x in c.execute(q,args)]
def one(q,args=()):
 result=rows(q,args);return result[0] if result else None
def audit(action,reference):execute('INSERT INTO audit(actor,action,reference,at) VALUES(?,?,?,?)',(g.user.get('sub','system') if hasattr(g,'user') else 'system',action,str(reference),stamp()))
def require_user():
 if not g.user:abort(401,'Choose a synthetic demo role to continue.')
def require_staff():
 require_user()
 if not g.staff and not getattr(g,'workspace_verification_authorized',False):abort(403,'This action requires the verifier or supervisor role.')
def page(name,**kw):return render_template(name,user=g.user,staff=g.staff,csrf=g.session['csrf'],base=BASE,prefix=PREFIX,**kw)
def clean(value,length=100):
 value=(value or '').strip()
 if len(value)>length:raise ValueError('Field exceeds its maximum length.')
 return value
def is_maker(profile,actor):return profile['sub']==actor or profile.get('last_editor')==actor
with db() as c:
 c.executescript('''
 CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,data TEXT,expires INTEGER);
 CREATE TABLE IF NOT EXISTS profiles(sub TEXT PRIMARY KEY,ref TEXT UNIQUE,household_ref TEXT UNIQUE,data TEXT,status TEXT DEFAULT 'pending_review',sync_status TEXT DEFAULT 'not_started',error TEXT,portal_partner INTEGER,mapping TEXT,updated TEXT,last_editor TEXT);
 CREATE TABLE IF NOT EXISTS programs(id INTEGER PRIMARY KEY,mnemonic TEXT UNIQUE,name TEXT,amount REAL,max_income REAL,min_members INTEGER,portal_id INTEGER,cycle_id INTEGER,benefit_id INTEGER,status TEXT DEFAULT 'ACTIVE');
 CREATE TABLE IF NOT EXISTS applications(id INTEGER PRIMARY KEY AUTOINCREMENT,sub TEXT,program INTEGER,status TEXT DEFAULT 'pending_review',portal_info INTEGER,portal_membership INTEGER,pbms_list INTEGER,error TEXT,created TEXT,UNIQUE(sub,program));
 CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,actor TEXT,action TEXT,reference TEXT,at TEXT);
 CREATE TABLE IF NOT EXISTS districts(id TEXT PRIMARY KEY,name TEXT UNIQUE,division TEXT,aliases TEXT,country_code TEXT DEFAULT 'IND',state_code TEXT DEFAULT 'IN-KA');
 CREATE TABLE IF NOT EXISTS consents(id TEXT PRIMARY KEY,household TEXT,scope TEXT,status TEXT,updated TEXT);
 CREATE TABLE IF NOT EXISTS partners(id TEXT PRIMARY KEY,name TEXT,service TEXT,status TEXT,synthetic INTEGER DEFAULT 1);
 ''')
 for d in DISTRICTS.values():c.execute('INSERT OR IGNORE INTO districts(id,name,division,aliases) VALUES(?,?,?,?)',(d['id'],d['name'],d['division'],json.dumps(d['aliases'])))

ROLEMAP={'officer':['kdbt-registration-officer'],'verifier':['kdbt-verification-officer','kdbt-intake-reviewer'],'supervisor':['kdbt-programme-supervisor','kdbt-intake-reviewer'],'citizen':[]}
@app.before_request
def context():
 if request.path==PREFIX+'/api/analytics/context':return
 sid=request.cookies.get('KDBT-DEMO');s=one('SELECT * FROM sessions WHERE id=? AND expires>?',(sid or '',int(time.time())))
 g.session=json.loads(s['data']) if s else {};g.sid=sid if s else secrets.token_urlsafe(32);g.user=g.session.get('user',{});g.staff='kdbt-intake-reviewer' in g.user.get('roles',[])
 g.session.setdefault('csrf',secrets.token_urlsafe(32))
 if request.method in ('POST','PUT','DELETE') and not secrets.compare_digest(request.form.get('csrf',''),g.session['csrf']):abort(403,'Session expired. Reload before trying again.')
@app.after_request
def cookies(res):
 if hasattr(g,'session'):
  execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?)',(g.sid,json.dumps(g.session),int(time.time())+7200))
  res.set_cookie('KDBT-DEMO',g.sid,max_age=7200,httponly=True,samesite='Lax',secure=False)
 res.headers['Cache-Control']='no-store';res.headers['X-Content-Type-Options']='nosniff';res.headers['X-Frame-Options']='DENY';res.headers['Referrer-Policy']='same-origin'
 return res
@app.get('/')
def hub():return send_from_directory(BASE_DIR/'hub-assets','index.html')
@app.get('/assets/<path:name>')
def assets(name):
 if name in ['site.js','workspace.js','site-shell.js']:return send_from_directory(BASE_DIR/'persona-ui/dist',name)
 return send_from_directory(BASE_DIR/'assets',name)
@app.get('/favicon.ico')
def favicon():return send_from_directory(BASE_DIR/'assets','favicon.ico')
@app.get(PREFIX+'/static/workspace.js')
def workspace_bundle():return send_from_directory(BASE_DIR/'persona-ui/dist','workspace.js')
@app.get('/kdbt-brand/<path:name>')
def brand_assets(name):
 if name.endswith('.js'):return send_from_directory(BASE_DIR/'persona-ui/dist',name)
 return send_from_directory(BASE_DIR/'hub-assets',name)
@app.get(PREFIX+'/health')
def health():return {'status':'ok','platform':FULL_NAME,'synthetic':True,'districts':31,'storage':'isolated Karnataka SQLite'}
@app.get(PREFIX+'/login')
def login():return page('login.html',rolemap=ROLEMAP)
@app.post(PREFIX+'/login')
def sign_in():
 role=request.form.get('role');identity=request.form.get('identity','primary')
 if role not in ROLEMAP or identity not in ['primary','second']:abort(400)
 sub=('KA-DEMO-HH-001' if identity=='primary' else 'KA-NEW-APPLICANT') if role=='citizen' else 'demo-'+role+'-'+identity
 g.session['user']={'sub':sub,'name':{'officer':'Kavya · Registration officer','verifier':'Ravi · Verification officer','supervisor':'Anita · Programme supervisor','citizen':'Lakshmi Gowda · Demo applicant'}[role]+(' (alternate)' if identity=='second' else ''),'roles':ROLEMAP[role],'email':sub+'@example.invalid'}
 g.session['mode']='beneficiary' if role=='citizen' else 'staff';g.session['role']=role;g.session['csrf']=secrets.token_urlsafe(32)
 audit('demo_role_signed_in',role)
 return redirect(PREFIX+'/workspace')
@app.post(PREFIX+'/logout')
def logout():g.session.clear();return redirect('/')
@app.get(PREFIX+'/')
def home():
 p=one('SELECT * FROM profiles WHERE sub=?',(g.user.get('sub',''),));apps=rows('SELECT a.*,p.name FROM applications a JOIN programs p ON p.id=a.program WHERE sub=?',(g.user.get('sub',''),))
 return page('home.html',profile=p,programs=rows("SELECT * FROM programs WHERE status='ACTIVE'"),applications=apps)
@app.get(PREFIX+'/profile')
def profile():
 require_user()
 if g.session['mode']!='beneficiary':abort(403,'Use the citizen demo role to register your household.')
 p=one('SELECT * FROM profiles WHERE sub=?',(g.user['sub'],))
 return page('profile.html',profile=p,data=json.loads(p['data']) if p else {},states=[(d['id'],d['name']) for d in DISTRICTS.values()],geocatalogue=CATALOGUE)
@app.post(PREFIX+'/profile')
def profile_save():
 require_user()
 if g.session['mode']!='beneficiary':abort(403)
 with LOCK:
  p=one('SELECT * FROM profiles WHERE sub=?',(g.user['sub'],))
  if p and p['status']=='approved':abort(409,'Approved profile is locked. Contact the reviewer.')
  try:
   members=[]
   for i in range(8):
    given=clean(request.form.get(f'given_{i}'));family=clean(request.form.get(f'family_{i}'))
    if not given and not family:continue
    if not given or not family:raise ValueError('Each member needs a given and family name.')
    birth=datetime.date.fromisoformat(request.form.get(f'birth_{i}',''));gender=request.form.get(f'gender_{i}')
    if not 1900<=birth.year or birth>datetime.date.today() or gender not in ['Female','Male','Other']:raise ValueError('Check the member date of birth and gender.')
    members.append(dict(given=given,family=family,birth_date=str(birth),gender=gender,ref='KA-I-'+uuid.uuid5(uuid.NAMESPACE_URL,g.user['sub']+str(i)).hex[:16]))
   if not members or not request.form.get('synthetic'):raise ValueError('Add a fictional member and confirm synthetic data use.')
   district=DISTRICTS.get(request.form.get('state'));income=float(request.form.get('income',''))
   if not district or not math.isfinite(income) or not 0<=income<=1e9:raise ValueError('Choose a valid Karnataka district and monthly income.')
   data=dict(members=members,state=district['id'],state_name=district['name'],district_id=district['id'],district_name=district['name'],country_code='IND',state_code='IN-KA',community=clean(request.form.get('community')),household_name=clean(request.form.get('household_name')),monthly_income=income,email=g.user['email'],synthetic=True)
   if not data['household_name']:raise ValueError('Enter a household name.')
   import karnataka_geography
   data['geography']=karnataka_geography.capture(request.form,data)
  except (ValueError,TypeError) as e:return page('message.html',title='Please check the form',message=str(e),back=PREFIX+'/profile'),400
  hh=p['household_ref'] if p else 'KA-HH-'+uuid.uuid4().hex[:12]
  execute("INSERT INTO profiles(sub,ref,household_ref,data,status,updated,last_editor) VALUES(?,?,?,?,'pending_review',?,?) ON CONFLICT(sub) DO UPDATE SET data=excluded.data,status='pending_review',sync_status='not_started',error=NULL,updated=excluded.updated,last_editor=excluded.last_editor",(g.user['sub'],members[0]['ref'],hh,json.dumps(data),stamp(),g.user['sub']))
  audit('registration_submitted',hh)
 return redirect(PREFIX+'/')
def sync_profile(sub):execute("UPDATE profiles SET sync_status='complete',mapping=?,error=NULL WHERE sub=?",(json.dumps({'mode':'local_simulation','registry':'KarnatakaDBT synthetic registry'}),sub))
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
 with LOCK:
  p=one('SELECT * FROM profiles WHERE sub=?',(sub,))
  if not p:abort(404)
  if action not in ['approve','reject','retry']:abort(404)
  if is_maker(p,g.user['sub']):abort(403,'An independent reviewer must decide a record you made.')
  if (action!='retry' and p['status']!='pending_review') or (action=='retry' and p['status']!='approved'):abort(409,'Record status changed. Refresh before deciding.')
  if action=='reject':
   reason=clean(request.form.get('reason'),500)
   if len(reason)<10:abort(400,'Give a correction reason of at least 10 characters.')
   execute("UPDATE profiles SET status='rejected',error=?,updated=? WHERE sub=?",(reason,stamp(),sub))
  else:
   execute("UPDATE profiles SET status='approved',updated=? WHERE sub=?",(stamp(),sub));sync_profile(sub)
  audit('registration_'+action,sub)
 return redirect(PREFIX+'/staff')
@app.post(PREFIX+'/apply/<int:pid>')
def apply_program(pid):
 require_user();p=one('SELECT * FROM profiles WHERE sub=?',(g.user['sub'],));programme=one("SELECT * FROM programs WHERE id=? AND status='ACTIVE'",(pid,))
 if g.session['mode']!='beneficiary' or not p or p['status']!='approved' or p['sync_status']!='complete' or not programme:abort(409,'An approved household and active programme are required.')
 execute('INSERT OR IGNORE INTO applications(sub,program,created) VALUES(?,?,?)',(g.user['sub'],pid,stamp()));audit('programme_application',pid);return redirect(PREFIX+'/')
@app.post(PREFIX+'/staff/program')
def program_create():
 require_staff()
 if g.session.get('role')!='supervisor':abort(403,'Programme creation requires the supervisor role.')
 try:
  name=clean(request.form.get('name'));mnemonic=clean(request.form.get('mnemonic'));amount=float(request.form.get('amount'));income=float(request.form.get('max_income'));minimum=int(request.form.get('min_members'))
  if not name or not mnemonic.replace('_','').isalnum() or not math.isfinite(amount+income) or not 0<amount<=1e6 or not 0<=income<=1e9 or not 1<=minimum<=8:raise ValueError()
  execute('INSERT INTO programs(mnemonic,name,amount,max_income,min_members) VALUES(?,?,?,?,?)',('KA_'+mnemonic,name,amount,income,minimum));audit('programme_created',mnemonic)
 except (ValueError,sqlite3.IntegrityError):abort(400,'Check programme fields and use a unique mnemonic.')
 return redirect(PREFIX+'/staff')
@app.post(PREFIX+'/staff/application/<int:aid>/<action>')
def application_decision(aid,action):
 require_staff()
 with LOCK:
  a=one('SELECT * FROM applications WHERE id=?',(aid,))
  if not a:abort(404)
  if action=='check' and a['status']=='pending_review':
   d=json.loads(one('SELECT data FROM profiles WHERE sub=?',(a['sub'],))['data']);p=one('SELECT * FROM programs WHERE id=?',(a['program'],))
   status='eligible' if d['monthly_income']<=p['max_income'] and len(d['members'])>=p['min_members'] else 'not_eligible'
  elif action=='enroll' and a['status']=='eligible':status='enrolled'
  elif action=='reject' and a['status'] in ['pending_review','eligible']:status='rejected'
  else:abort(409,'Action is not available in the current status.')
  execute('UPDATE applications SET status=?,error=NULL WHERE id=?',(status,aid));audit('application_'+action,aid)
 return redirect(PREFIX+'/staff')

# Reuse the knowledge, analytics, persona and partner engines.
import karnataka_geography,registration_workspaces,knowledge_management,platform_analytics,partner_simulation,local_ai
for module in [registration_workspaces,karnataka_geography,knowledge_management,platform_analytics,partner_simulation,local_ai]:module.install(sys.modules[__name__])
import runtime_ai
runtime_ai.configure(local_ai)
import external_registers
external_registers.install(sys.modules[__name__])
import analytics_completion
analytics_completion.install(sys.modules[__name__])
import services
services.install(sys.modules[__name__])

def seed():
 names=['Lakshmi','Kavya','Deepa','Asha','Savitha','Roopa','Shobha','Geetha','Suma','Anitha','Meera','Nandini','Basavaraj','Siddappa','Mallappa','Manjunath','Ramesh','Shivanna','Prakash','Nagaraj','Mahesh','Ganesh','Ravi','Sunitha','Kavitha','Bhagya','Chandramma','Yellamma','Renuka','Lalitha','Saraswathi','Fathima','Ayesha','Nazia','Saira','Mohammed','Irfan','Abdul','Rehman','Mary','Rosy','Agnes','Joseph','John','David','Sneha','Priya','Sahana','Divya','Rakshith','Puneeth','Darshan','Hemanth','Pooja','Bharathi','Vidya','Uma','Akkamma','Parvathi','Kamala']
 families=['Gowda','Patil','Rao','Hegde','Naik','Shetty','Kulkarni','Desai','Poojary','Billava','Acharya','Bhat','Upadhyaya','Kamath','Pai','Shenoy','Nayak','Kumar','Das','Chalavadi','Madiga','Holeya','Lamani','Rathod','Chavan','Jadhav','Kambli','Koppad','Angadi','Koti','Biradar','Hiremath','Mathad','Swamy','Devaraj','Basavaraj','Siddappa','Shivanna','Raj','Pillai','D’Souza','Fernandes','Pereira','Menezes','Lobo','D’Costa','Khan','Shaikh','Syed','Ahmed','Pasha','Sharif','Hussain','Ansari','Gownder','Nair','Devadiga','Kotian','Suvarna','Bhandari']
 with db() as c:
  for i,(name,amount,income) in enumerate([('Gruha Lakshmi — synthetic DBT demonstration',2000,25000),('Anna Bhagya — synthetic food support',850,18000),('Social Security Pension — synthetic demonstration',1200,15000),('Farmer Support — synthetic demonstration',2000,30000),('Student Scholarship — synthetic demonstration',1500,22000)],1):
   c.execute('INSERT OR IGNORE INTO programs(id,mnemonic,name,amount,max_income,min_members) VALUES(?,?,?,?,?,1)',(i,'KA_DEMO_'+str(i),name,amount,income))
  for dnum,d in enumerate(DISTRICTS.values()):
   for j in range(40):
    n=dnum*40+j+1;sub=f'KA-DEMO-HH-{n:03}';given=names[(n-1)%len(names)];family=families[((n-1)*7+(n-1)//len(names))%len(families)];members=[dict(given=given,family=family,birth_date='1988-04-12',gender='Male' if given in {'Basavaraj','Siddappa','Mallappa','Manjunath','Ramesh','Shivanna','Prakash','Nagaraj','Mahesh','Ganesh','Ravi','Mohammed','Irfan','Abdul','Rehman','Joseph','John','David','Rakshith','Puneeth','Darshan','Hemanth'} else 'Female',ref=f'KA-I-{n:04}-01'),dict(given=['Arjun','Kiran','Rahul','Nikhil','Ajay','Imran','Roshan','Chethan','Akash','Naveen','Suhas','Vinay'][n%12],family=family,birth_date='2012-08-05',gender='Male',ref=f'KA-I-{n:04}-02'),dict(given=['Ananya','Sahana','Chaitra','Nidhi','Keerthana','Fiza','Maria','Rashmi','Shravya','Bhoomika','Tejaswini','Sanjana'][n%12],family=family,birth_date='2016-02-20',gender='Female',ref=f'KA-I-{n:04}-03')]
    status=['approved','pending_review','rejected','approved','approved'][j%5];geo={'district_id':d['id'],'district_name':d['name'],'zone_id':d['zone_id'],'zone_name':d['division'],'state_id':d['id'],'state_name':d['name'],'lga_id':None,'lga_name':None,'ward':None,'latitude':None,'longitude':None,'accuracy_m':None,'coordinate_source':'not_captured','coordinate_verified':False,'country_code':'IND','region_code':'IN-KA'}
    data=dict(household_name=given+' '+family+' household',state=d['id'],state_name=d['name'],district_id=d['id'],district_name=d['name'],country_code='IND',state_code='IN-KA',community=f'Synthetic community {j+1:02}',monthly_income=8500+j*3500,members=members,geography=geo,synthetic=True,email=sub.lower()+'@example.invalid')
    c.execute('INSERT OR IGNORE INTO profiles VALUES(?,?,?,?,?,?,?,?,?,?,?)',(sub,members[0]['ref'],sub,json.dumps(data),status,'complete' if status=='approved' else 'not_started','Confirm the synthetic community before resubmitting.' if status=='rejected' else None,n,json.dumps({'mode':'local_simulation'}),stamp(),None))
    if status=='approved':
     program=c.execute('SELECT max_income FROM programs WHERE id=?',(n%5+1,)).fetchone()
     application_status=['enrolled','eligible','pending_review'][j%3] if data['monthly_income']<=program['max_income'] else 'not_eligible'
     c.execute('INSERT OR IGNORE INTO applications(sub,program,status,created) VALUES(?,?,?,?)',(sub,n%5+1,application_status,stamp()))
    c.execute('INSERT OR IGNORE INTO consents VALUES(?,?,?,?,?)',('KA-CONSENT-'+str(n),sub,'Synthetic DBT demonstration','granted',stamp()))
  for sid,name in [('identity','Identity verification simulator'),('social-register','Karnataka social registry simulator'),('programme','DBT programme engine'),('treasury','Karnataka treasury simulator'),('account','Bank validation simulator'),('payment','Payment simulator'),('notification','Notification simulator'),('grievance','Grievance service'),('reconciliation','Reconciliation simulator')]:c.execute('INSERT OR IGNORE INTO partners VALUES(?,?,?,?,1)',('KA-PARTNER-'+sid,name,sid,'sandbox_active'))
 analytics_snapshot()
seed()
@app.errorhandler(Exception)
def error(e):
 code=e.code if isinstance(e,HTTPException) else 500
 if code==500:app.logger.exception('Request failed')
 message=e.description if isinstance(e,HTTPException) else 'The request could not be completed. Your saved records are retained.'
 if '/api/' in request.path:return {'error':message},code
 return page('message.html',title='Action needs attention',message=message,back=PREFIX+'/'),code
import next_frontend
next_frontend.install(sys.modules[__name__])
if __name__=='__main__':
 from waitress import serve
 print('KarnatakaDBT ready: http://127.0.0.1:18210',flush=True)
 serve(app,host=os.environ.get('KDBT_BIND','127.0.0.1'),port=int(os.environ.get('PORT','18210')),threads=8)

