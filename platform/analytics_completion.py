"""Unified simulation reporting, anonymous help telemetry and measured learning.

No question text, answers, beneficiary payloads or raw user identities are stored.
Public help events are untrusted anonymous usage, not authenticated staff actions.
"""
def aggregate_rows(data):
 rows=[]
 def emit(section,value,path=''):
  if isinstance(value,dict):
   for name,item in value.items():emit(section,item,path+'.'+name if path else name)
  elif isinstance(value,list):
   for index,item in enumerate(value):
    label=str(item.get('label',item.get('source',index))) if isinstance(item,dict) else str(index)
    if isinstance(item,dict):
     for name,number in item.items():
      if name not in ['label','source']:emit(section,number,path+'.'+label+'.'+name)
    else:emit(section,item,path+'.'+label)
  elif isinstance(value,(int,float)) or value is None:
   scope='Synthetic integer paise' if path.endswith('_minor') else 'Aggregate synthetic platform or observed usage; see dashboard for filter scope'
   rows.append((section,path,value,scope))
 for section in ['context','ai','training','connected','legacy_partner']:
  emit(section,data[section])
 return rows

import collections
import datetime as dt
import hashlib
import io
import csv
import json
import secrets
import sqlite3
import statistics
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from flask import Blueprint, abort, g, request, redirect

COURSES={
 'dbt-workflow':{'title':'DBT workflow essentials','module':'platform','version':1,'questions':[
  {'text':'What does household registration approval establish?','options':['Payment has settled','Registration details passed review; benefit approval is separate','Every programme has accepted the household'],'correct':1},
  {'text':'What should happen when an external evidence source is unavailable?','options':['Automatically reject the household','Assume the household is eligible','Record the exception and retry or review it'],'correct':2},
  {'text':'When is a transfer reconciled?','options':['As soon as an instruction is accepted','When bank settlement evidence agrees with the instruction','When registration is saved'],'correct':1},
  {'text':'How should a duplicate bank callback be handled?','options':['Ignore the duplicate without creating another transfer','Pay again','Delete the audit trail'],'correct':0},
  {'text':'What should you do before acting on an AI answer?','options':['Treat it as a sanction','Check the published sources and your authority','Skip independent review'],'correct':1}]},
 'source-evidence':{'title':'Source evidence and geography','module':'geography','version':1,'questions':[
  {'text':'What identifies the source of a decision?','options':['The colour of the dashboard','A source record reference, version and fetch time','Only a household name'],'correct':1},
  {'text':'What does a district density colour measure?','options':['Records per mapped area','A guaranteed fraud level','A legal land boundary'],'correct':0},
  {'text':'What happens to frozen evidence when a source is corrected?','options':['It silently changes','It is deleted','It stays unchanged; a fresh lookup records new evidence'],'correct':2},
  {'text':'Can a simulation schema be assumed to be an official production contract?','options':['Yes, if it has columns','Only after the owning department confirms the contract','Yes, if the website is online'],'correct':1},
  {'text':'Can a district code establish an exact household GPS point?','options':['No; coordinates need their own capture and provenance','Yes','Only if the income is known'],'correct':0}]},
}

def install(r):
 bp=Blueprint('analytics_completion',__name__)
 with r.db() as c:
  c.executescript('''
  CREATE TABLE IF NOT EXISTS context_usage(event_id TEXT PRIMARY KEY,event_name TEXT NOT NULL,host TEXT NOT NULL,module TEXT NOT NULL,article INTEGER,version INTEGER,session_key TEXT NOT NULL,helpful INTEGER,at TEXT NOT NULL);
  CREATE INDEX IF NOT EXISTS context_usage_time ON context_usage(at,module);
  CREATE TABLE IF NOT EXISTS context_daily(day TEXT NOT NULL,host TEXT NOT NULL,module TEXT NOT NULL,event_name TEXT NOT NULL,helpful INTEGER NOT NULL,events INTEGER NOT NULL,PRIMARY KEY(day,host,module,event_name,helpful));
  CREATE TABLE IF NOT EXISTS ai_interactions(id TEXT PRIMARY KEY,session_key TEXT NOT NULL,module TEXT NOT NULL,mode TEXT NOT NULL,status TEXT NOT NULL,source_count INTEGER NOT NULL,cited INTEGER NOT NULL,latency_ms INTEGER NOT NULL,at TEXT NOT NULL);
  CREATE INDEX IF NOT EXISTS ai_interactions_time ON ai_interactions(at,module);
  CREATE TABLE IF NOT EXISTS ai_feedback(answer_id TEXT PRIMARY KEY REFERENCES ai_interactions(id),helpful INTEGER,resolved INTEGER,at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS training_attempts(id TEXT PRIMARY KEY,actor_key TEXT NOT NULL,course TEXT NOT NULL,module TEXT NOT NULL,version INTEGER NOT NULL,score INTEGER NOT NULL,maximum INTEGER NOT NULL,passed INTEGER NOT NULL,at TEXT NOT NULL,answers_key TEXT NOT NULL);
  CREATE INDEX IF NOT EXISTS training_attempts_time ON training_attempts(at,module);
  ''')
 def key(value):return hashlib.sha256(('KarnatakaDBT analytics:'+value).encode()).hexdigest()
 def staff():
  r.require_user()
  roles={x.replace('iqs-','kdbt-') for x in g.user.get('roles',[])}
  if g.session.get('mode')!='staff' or not (g.staff or roles & {'kdbt-registration-officer','kdbt-verification-officer','kdbt-programme-supervisor'}):abort(403,'Assigned staff analytics access required.')
 def public_context():
  # Browser callers must be same origin; there is no cross-origin CORS grant.
  origin=urlsplit(request.headers.get('Origin',''))
  host=request.host.split(':',1)[0].lower()
  allowed=host in ['localhost','127.0.0.1'] or host=='localhost:8443' or host.endswith('.localhost:8443')
  if not allowed or origin.netloc.lower()!=request.host.lower() or origin.scheme not in ['https','http'] or request.headers.get('Sec-Fetch-Site','same-origin') not in ['same-origin','none']:abort(403,'Same-origin help telemetry required.')
  if host not in ['localhost','127.0.0.1'] and origin.scheme!='https':abort(403)
  try:eid=str(uuid.UUID(request.form.get('event_id','')))
  except ValueError:abort(400,'Valid event ID required.')
  event=request.form.get('event_name')
  if event not in ['help_opened','guide_shown','context_feedback','help_unmapped']:abort(400,'Unsupported help event.')
  module=request.form.get('module','platform')
  if module not in __import__('knowledge_management').MODULES:abort(400,'Unknown service.')
  article=None;version=None;helpful=None
  if event in ['guide_shown','context_feedback']:
   try:article=int(request.form.get('article_id',''));version=int(request.form.get('version',''))
   except ValueError:abort(400,'Published article and version required.')
   row=r.one("SELECT * FROM km_articles WHERE id=? AND published IS NOT NULL AND status!='archived'",(article,))
   if not row or row['published_version']!=version:abort(409,'Guidance version changed.')
   if json.loads(row['published']).get('visibility')=='staff':abort(403,'Private guidance is excluded from anonymous context telemetry.')
   module=json.loads(row['published'])['module']
  if event=='context_feedback':
   if request.form.get('helpful') not in ['0','1']:abort(400,'Choose a feedback value.')
   helpful=int(request.form['helpful'])
  sid=request.cookies.get('KDBT-HELP','')
  if not 20<=len(sid)<=100:sid=secrets.token_urlsafe(24)
  session=key(sid);at=r.stamp()
  with r.db() as c:
   c.execute('BEGIN IMMEDIATE')
   if c.execute('SELECT 1 FROM context_usage WHERE event_id=?',(eid,)).fetchone():accepted=False
   else:
    cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(hours=1)).isoformat()
    if c.execute('SELECT count(*) FROM context_usage WHERE session_key=? AND at>=?',(session,cutoff)).fetchone()[0]>=120:abort(429,'Help usage event limit reached.')
    if c.execute('SELECT count(*) FROM context_usage WHERE at>=?',(cutoff,)).fetchone()[0]>=10000:abort(429,'Help usage collection is at capacity.')
    duplicate=event=='context_feedback' and c.execute("SELECT 1 FROM context_usage WHERE session_key=? AND article=? AND version=? AND event_name='context_feedback' AND substr(at,1,10)=?",(session,article,version,at[:10])).fetchone()
    accepted=not bool(duplicate)
    if accepted:
     c.execute('INSERT INTO context_usage VALUES(?,?,?,?,?,?,?,?,?)',(eid,event,host,module,article,version,session,helpful,at))
     c.execute('INSERT INTO context_daily VALUES(?,?,?,?,?,1) ON CONFLICT(day,host,module,event_name,helpful) DO UPDATE SET events=events+1',(at[:10],host,module,event,-1 if helpful is None else helpful))
  response=r.app.make_response({'accepted':accepted,'anonymous':True});response.set_cookie('KDBT-HELP',sid,httponly=True,secure=host not in ['localhost','127.0.0.1'],samesite='Strict',path='/',max_age=86400)
  return response
 bp.add_url_rule(r.PREFIX+'/api/analytics/context','context_event',public_context,methods=['POST'])

 @bp.before_app_request
 def start_ai_clock():
  if request.path==r.PREFIX+'/api/ai/chat':g.ai_started=time.perf_counter()
 @bp.after_app_request
 def record_ai(response):
  if request.path!=r.PREFIX+'/api/ai/chat' or not getattr(g,'user',None) or not hasattr(g,'ai_started'):return response
  module=request.form.get('module','platform')
  if module not in __import__('knowledge_management').MODULES:module='platform'
  payload=response.get_json(silent=True) or {};successful=response.status_code==200
  rid=str(uuid.uuid4());sources=payload.get('sources',[]) if successful else []
  mode=payload.get('generation_mode','unknown') if successful else 'none'
  with r.db() as c:c.execute('INSERT INTO ai_interactions VALUES(?,?,?,?,?,?,?,?,?)',(rid,key(g.sid),module,mode,'answered' if successful and sources else 'no_guidance' if successful else 'error',len(sources),int(payload.get('source_label')=='Published sources'),round((time.perf_counter()-g.ai_started)*1000),r.stamp()))
  if successful:payload['answer_id']=rid;response.set_data(r.app.json.dumps(payload));response.mimetype='application/json'
  return response

 @bp.post(r.PREFIX+'/api/analytics/ai-feedback')
 def ai_feedback():
  r.require_user();rid=request.form.get('answer_id','');row=r.one('SELECT * FROM ai_interactions WHERE id=?',(rid,))
  if not row or row['session_key']!=key(g.sid):abort(403,'Feedback is limited to your own answer session.')
  values={}
  for field in ['helpful','resolved']:
   value=request.form.get(field)
   if value is not None and value not in ['0','1']:abort(400,'Feedback values must be 0 or 1.')
   values[field]=int(value) if value is not None else None
  if all(v is None for v in values.values()):abort(400,'Choose a feedback value.')
  with r.db() as c:c.execute('INSERT INTO ai_feedback VALUES(?,?,?,?) ON CONFLICT(answer_id) DO UPDATE SET helpful=COALESCE(excluded.helpful,ai_feedback.helpful),resolved=COALESCE(excluded.resolved,ai_feedback.resolved),at=excluded.at',(rid,values['helpful'],values['resolved'],r.stamp()))
  return {'saved':True}

 @bp.get(r.PREFIX+'/learning')
 def learning():
  if not g.user:return redirect(r.PREFIX+'/login?mode=staff&learning=1')
  actor=key(g.user['sub'])
  attempts=r.rows('SELECT course,score,maximum,passed,at FROM training_attempts WHERE actor_key=? ORDER BY at DESC LIMIT 30',(actor,))
  # Correct answer indices stay server-side.
  courses={cid:{**course,'questions':[{'text':q['text'],'options':q['options']} for q in course['questions']]} for cid,course in COURSES.items()}
  return r.page('learning.html',courses=courses,attempts=attempts,request_ids={cid:str(uuid.uuid4()) for cid in courses},result=None)

 @bp.post(r.PREFIX+'/learning/<course_id>')
 def assess(course_id):
  r.require_user();course=COURSES.get(course_id)
  if not course:abort(404)
  try:rid=str(uuid.UUID(request.form.get('request_id','')))
  except ValueError:abort(400,'Assessment request ID required.')
  actor=key(g.user['sub']);answers=[]
  try:
   for index,q in enumerate(course['questions']):
    value=int(request.form.get('q'+str(index),''))
    if value not in range(len(q['options'])):raise ValueError()
    answers.append(value)
  except ValueError:abort(400,'Answer every assessment question.')
  score=sum(answer==q['correct'] for answer,q in zip(answers,course['questions']));maximum=len(answers)
  with r.db() as c:
   c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM training_attempts WHERE id=?',(rid,)).fetchone()
   if old:
    if old['actor_key']!=actor or old['course']!=course_id or old['answers_key']!=key(json.dumps(answers)):abort(409,'Assessment ID already used with different answers.')
    result=dict(old)
   else:
    cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(hours=1)).isoformat()
    if c.execute('SELECT count(*) FROM training_attempts WHERE actor_key=? AND at>=?',(actor,cutoff)).fetchone()[0]>=10:abort(429,'Please wait before repeating the assessment.')
    result={'id':rid,'actor_key':actor,'course':course_id,'module':course['module'],'version':course['version'],'score':score,'maximum':maximum,'passed':int(score/maximum>=.8),'at':r.stamp(),'answers_key':key(json.dumps(answers))}
    c.execute('INSERT INTO training_attempts VALUES(?,?,?,?,?,?,?,?,?,?)',tuple(result.values()))
  feedback=[{'text':q['text'],'correct':q['options'][q['correct']],'passed':answer==q['correct']} for answer,q in zip(answers,course['questions'])]
  return r.page('learning.html',courses={},attempts=[],request_id=str(uuid.uuid4()),result={**result,'title':course['title'],'feedback':feedback})

 def extended(filters):
  start,end,module,state=filters['start'],filters['end'],filters['module'],filters['state']
  low=start+'T00:00:00';high=end+'T23:59:59.999999+00:00'
  args=(start,end,module) if module else (start,end)
  daily=r.rows("SELECT * FROM context_daily WHERE day>=? AND day<=? AND event_name IN ('help_opened','guide_shown','context_feedback','help_unmapped')"+(' AND module=?' if module else ''),args)
  totals=collections.Counter();hosts=collections.Counter()
  for row in daily:
   totals[row['event_name']]+=row['events'];hosts[row['host']]+=row['events']
   if row['event_name']=='context_feedback' and row['helpful']==1:totals['helpful']+=row['events']
  ai=r.rows('SELECT a.*,f.helpful,f.resolved FROM ai_interactions a LEFT JOIN ai_feedback f ON a.id=f.answer_id WHERE a.at>=? AND a.at<=?'+(' AND a.module=?' if module else ''),(low,high,module) if module else (low,high))
  latency=sorted(x['latency_ms'] for x in ai if x['status']=='answered')
  def rate(n,d):return round(100*n/d,1) if d else None
  votes=[x for x in ai if x['helpful'] is not None];resolved=[x for x in ai if x['resolved'] is not None]
  attempts=r.rows('SELECT * FROM training_attempts WHERE at>=? AND at<=?'+(' AND module=?' if module else '')+' ORDER BY at,id',(low,high,module) if module else (low,high))
  learners={};pairs={}
  for x in attempts:learners.setdefault(x['actor_key'],[]).append(x);pairs.setdefault((x['actor_key'],x['course'],x['version']),[]).append(x)
  gains=[100*items[-1]['score']/items[-1]['maximum']-100*items[0]['score']/items[0]['maximum'] for items in pairs.values() if len(items)>1]
  result={'context':{'usage':dict(totals),'by_host':[{'label':h,'count':n} for h,n in sorted(hosts.items())],'helpfulness':rate(totals['helpful'],totals['context_feedback']),'tracking_scope':'Anonymous same-origin help events, not verified unique people'},
   'ai':{'requests':len(ai),'answered':sum(x['status']=='answered' for x in ai),'errors':sum(x['status']=='error' for x in ai),'no_guidance':sum(x['status']=='no_guidance' for x in ai),'with_published_citations':sum(bool(x['cited']) for x in ai),'modes':dict(collections.Counter(x['mode'] for x in ai)),'helpful_votes':len(votes),'helpfulness':rate(sum(x['helpful']==1 for x in votes),len(votes)),'resolution_votes':len(resolved),'self_reported_resolution':rate(sum(x['resolved']==1 for x in resolved),len(resolved)),'median_latency_ms':statistics.median(latency) if latency else None},
   'training':{'attempts':len(attempts),'learners':len(learners),'passed_attempts':sum(x['passed'] for x in attempts),'pass_rate':rate(sum(x['passed'] for x in attempts),len(attempts)),'average_score':round(sum(100*x['score']/x['maximum'] for x in attempts)/len(attempts),1) if attempts else None,'repeat_pairs':len(gains),'average_repeat_gain_points':round(sum(gains)/len(gains),1) if gains else None,'courses':[{'label':c['title'],'count':sum(x['course']==cid for x in attempts)} for cid,c in COURSES.items()]}}
  lab={'runs':0,'states':[],'funnel':[],'sources':[],'payments':{},'by_scheme':[],'scope':'Connected-register simulation; dates select runs created in the period; district applies to the household snapshot. Native programme filter does not apply.'}
  model=getattr(r,'external_register_model',None)
  if model and (model.root/'schemes.sqlite').exists():
   with model.connect(attached=True) as c:
    c.execute('BEGIN')
    runs=[dict(x) for x in c.execute('SELECT * FROM runs WHERE created_at>=? AND created_at<=?',(low,high))]
    if state:runs=[x for x in runs if (json.loads(x['snapshot'])['data'].get('district_name') or json.loads(x['snapshot'])['data'].get('state_name'))==state]
    ids={x['id'] for x in runs};lab['runs']=len(runs)
    lab['states']=[{'label':s,'count':n} for s,n in sorted(collections.Counter(x['state'] for x in runs).items())]
    lab['by_scheme']=[{'label':s,'count':n} for s,n in sorted(collections.Counter(x['scheme_id'] for x in runs).items())]
    lab['funnel']=[{'label':label,'count':sum(x['stage']>=i for x in runs)} for i,label in enumerate(__import__('register_contracts').STAGES)]
    source_stats={}
    for x in c.execute('SELECT * FROM evidence'):
     if x['run_id'] not in ids:continue
     row=source_stats.setdefault(x['source'],collections.Counter());row['checks']+=1;row[x['status']]+=1
    lab['sources']=[{'source':s,**dict(v)} for s,v in sorted(source_stats.items())]
    current={x['id']:x['state'] for x in runs}
    sanctions=[dict(x) for x in c.execute('SELECT * FROM schemes.sanctions') if x['run_id'] in ids]
    reservations=[dict(x) for x in c.execute('SELECT * FROM treasury.reservations') if x['run_id'] in ids]
    instructions=[dict(x) for x in c.execute('SELECT * FROM bank.instructions') if x['run_id'] in ids];mapping={x['instruction_id']:x for x in instructions}
    settlements=[dict(x) for x in c.execute('SELECT * FROM bank.settlements') if x['instruction_id'] in mapping]
   lab['payments']={'sanctioned_minor':sum(x['amount_minor'] for x in sanctions),'reserved_minor':sum(x['amount_minor'] for x in reservations if x['status']=='reserved'),'released_minor':sum(x['amount_minor'] for x in reservations if x['status']=='released'),'submitted_minor':sum(x['amount_minor'] for x in instructions),'settled_minor':sum(x['amount_minor'] for x in settlements if x['status']=='settled'),'reconciled_minor':sum(x['amount_minor'] for x in settlements if x['status']=='settled' and current[mapping[x['instruction_id']]['run_id']] in ['reconciled','completed']),'reversed_minor':sum(x['amount_minor'] for x in settlements if x['status']=='reversed'),'failed_instructions':sum(x['status']=='failed' for x in instructions),'currency':'INR'}
  result['connected']=lab
  legacy={'runs':0,'states':[],'settled_minor':0,'scope':'Legacy fixed-household partner simulator; date filter applies, district and native programme filters do not. Excluded from connected-register and intake totals.'}
  path=r.ROOT/'partner-simulation.sqlite'
  if path.exists():
   c=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
   try:
    c.row_factory=sqlite3.Row;rows=[dict(x) for x in c.execute('SELECT * FROM runs WHERE created_at>=? AND created_at<=?',(low,high))]
    legacy.update(runs=len(rows),states=[{'label':s,'count':n} for s,n in sorted(collections.Counter(x['state'] for x in rows).items())],settled_minor=sum(x['amount_minor'] for x in rows if x['state']=='settled'))
   finally:c.close()
  result['legacy_partner']=legacy
  metadata={x['key']:x['value'] for x in r.rows("SELECT * FROM analytics_metadata WHERE key LIKE 'native_collector_%'")}
  success=metadata.get('native_collector_success');age=None
  if success:
   try:age=(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(success)).total_seconds()
   except ValueError:pass
  result['collector']={'last_success':success,'last_attempt':metadata.get('native_collector_attempt'),'error':metadata.get('native_collector_error') or None,'fresh':age is not None and -60<=age<=600,'interval_minutes':5}
  return result
 r.analytics_extended_report=extended
 def maintenance():
  today=dt.datetime.now(dt.timezone.utc).date();raw=str(today-dt.timedelta(days=90));old=str(today-dt.timedelta(days=366))
  with r.db() as c:
   c.execute('DELETE FROM context_usage WHERE at<?',(raw,));c.execute('DELETE FROM context_daily WHERE day<?',(old,))
   c.execute('DELETE FROM ai_feedback WHERE answer_id IN (SELECT id FROM ai_interactions WHERE at<?)',(old,));c.execute('DELETE FROM ai_interactions WHERE at<?',(old,));c.execute('DELETE FROM training_attempts WHERE at<?',(old,))
 r.analytics_maintenance=maintenance
 r.analytics_export_rows=aggregate_rows

 @bp.get(r.PREFIX+'/api/analytics/extended')
 def api():
  staff();return r.analytics_full_report()['extended']
 @bp.get(r.PREFIX+'/api/analytics/extended.csv')
 def export():
  staff()
  if not (g.staff or 'kdbt-programme-supervisor' in {role.replace('iqs-','kdbt-') for role in g.user.get('roles',[])}):abort(403,'Aggregate exports require supervisor access.')
  data=r.analytics_full_report()['extended'];out=io.StringIO();writer=csv.writer(out);writer.writerow(['section','measure','value','scope'])
  writer.writerows(aggregate_rows(data))
  response=r.app.make_response(out.getvalue());response.mimetype='text/csv';response.headers['Content-Disposition']='attachment; filename=KarnatakaDBT-extended-analytics.csv';return response
 r.app.register_blueprint(bp)
