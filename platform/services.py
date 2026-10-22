import json,csv,io,uuid,datetime
from pathlib import Path
from flask import request,g,abort,redirect,send_from_directory
MODULES={
'register':('Social registry','People and households'),'registry':('Household administration','People and households'),'beneficiary':('Beneficiary portal','People and households'),
'pbms':('Programme management','Programmes and approvals'),'awe':('Approval workflows','Programmes and approvals'),'portal-admin':('Programme administration','Programmes and approvals'),
'odk':('Field data collection','Field work and insights'),'superset':('Advanced analytics','Field work and insights'),'master-data-ui':('Master data','Shared services'),
'partner-management':('Partner management','Shared services'),'consent-manager':('Consent manager','Shared services'),'staff-portal':('Staff portal','Shared services'),'iam-staff-ui':('Staff access administration','Shared services'),'schemas':('Schema explorer','Shared services'),'automation':('AI and automation','Shared services')}
def install(r):
 @r.app.get('/services/<module>')
 @r.app.get('/services/<module>/<path:tail>')
 def service(module,tail=''):
  if module not in MODULES:abort(404)
  if not g.user:return redirect(r.PREFIX+'/login?mode=staff')
  if module=='beneficiary':return redirect(r.PREFIX+'/')
  if g.session.get('mode')!='staff':abort(403,'Choose a staff demo role for this workspace.')
  consoles={'register':8446,'registry':8446,'awe':8453,'master-data-ui':8447,'partner-management':8448,'consent-manager':8449,'staff-portal':8451,'iam-staff-ui':8445}
  if module in consoles:return redirect('https://localhost:'+str(consoles[module])+('/' if module=='awe' else '/console/'))
  if module=='staff-portal':return redirect('/?persona='+g.session.get('role','all'))
  if module=='superset':return redirect(r.PREFIX+'/analytics')
  if module=='odk':return redirect('https://localhost:8443/')
  title,group=MODULES[module];columns=[];records=[];links=[]
  if module in ['register','registry']:
   columns=['Reference','Household','District','Division','Members','Status','Sync'];query=request.args.get('q','').strip().lower();district=request.args.get('district','')
   for p in r.rows('SELECT * FROM profiles ORDER BY household_ref'):
    d=json.loads(p['data'])
    if district and district!=d['state']:continue
    row=[p['household_ref'],d['household_name'],d['state_name'],d['geography']['zone_name'],len(d['members']),p['status'],p['sync_status']]
    if not query or query in ' '.join(map(str,row)).lower():records.append(row)
   links=[('Independent review queue',r.PREFIX+'/staff'),('District map',r.PREFIX+'/geography'),('Export synthetic households','/api/registry/export.csv')]
  elif module in ['pbms','portal-admin']:
   columns=['ID','Programme','Benefit INR','Maximum monthly income INR','Minimum members','Status']
   records=[[p['id'],p['name'],p['amount'],p['max_income'],p['min_members'],p['status']] for p in r.rows('SELECT * FROM programs')]
   links=[('Manage programmes and applications',r.PREFIX+'/staff'),('Payment simulation',r.PREFIX+'/simulation'),('Connected evidence and eligibility',r.PREFIX+'/register-lab')]
  elif module=='awe':
   columns=['Reference','Queue','Status','Next step']
   records=[[p['household_ref'],'Household review',p['status'],'Independent verifier decision'] for p in r.rows("SELECT * FROM profiles WHERE status='pending_review'")]+[[a['id'],'Programme application',a['status'],'Eligibility or enrollment review'] for a in r.rows("SELECT * FROM applications WHERE status!='enrolled'")]
   links=[('Open review workspace',r.PREFIX+'/workspace'),('Knowledge review',r.PREFIX+'/knowledge/admin')]
  elif module=='master-data-ui':
   columns=['Project code','District','Revenue division','Earlier / alternate names']
   records=[[d['id'],d['name'],d['division'],', '.join(d['aliases']) or '—'] for d in r.DISTRICTS.values()]
   links=[('Classification and source notes',r.PREFIX+'/districts'),('District catalogue JSON',r.PREFIX+'/api/geography/areas')]
  elif module=='partner-management':
   columns=['Partner ID','Partner','Service','Status'];records=[[p['id'],p['name'],p['service'],p['status']] for p in r.rows('SELECT * FROM partners')]
   links=[('Run partner scenarios',r.PREFIX+'/simulation'),('Contracts and schemas','/services/schemas')]
  elif module=='consent-manager':
   columns=['Consent','Household','Scope','Status','Updated'];records=[[p[k] for k in ['id','household','scope','status','updated']] for p in r.rows('SELECT * FROM consents')]
   links=[('Consent knowledge',r.PREFIX+'/knowledge?module=consent-manager')]
  elif module=='iam-staff-ui':
   columns=['Demo role','Assigned permissions','Boundary'];records=[[k,', '.join(v) or 'Own household','Local demonstration only'] for k,v in r.ROLEMAP.items()]
   links=[('Switch demo identity',r.PREFIX+'/login')]
  elif module=='schemas':
   columns=['Contract / schema','Format','View'];records=[[f.name,'JSON Schema' if '.schema.' in f.name else 'Example or OpenAPI','/schemas/'+f.name] for f in sorted((r.BASE_DIR.parent/'schemas').glob('*.json'))]
   links=[('Live platform database schema','/schemas/platform.sql'),('Complete structural catalogue','/schema-catalogue'),('Partner scenario console',r.PREFIX+'/simulation'),('Download schema bundle','/schemas/bundle.zip')]
  elif module=='automation':
   columns=['Automation','Mode','State'];records=[['Eligibility rules','Synthetic, deterministic','Ready'],['Registration and enrollment','Independent staff approval','Ready'],['Partner scenario orchestration','Nine isolated scenarios','Ready'],['Knowledge assistant','Published-guide retrieval; optional local language model','Ready'],['Publishing','Draft → independent review → publish','Ready'],['Analytics','Computed from isolated records','Ready']]
   links=[('Knowledge assistant',r.PREFIX+'/ai'),('Run automation cycle','/automation'),('View event log',r.PREFIX+'/staff')]
  return r.page('service.html',title=title,group=group,module=module,columns=columns,records=records,links=links,districts=r.DISTRICTS.values())
 @r.app.get(r.PREFIX+'/districts')
 def districts():return r.page('districts.html',catalogue=r.CATALOGUE)
 @r.app.get('/schemas/<path:name>')
 def schemas(name):
  r.require_user()
  if g.session.get('mode')!='staff':abort(403)
  if name=='platform.sql':
   result=[]
   for filename in ['intake.sqlite','partner-simulation.sqlite']:
    import sqlite3
    with sqlite3.connect(r.ROOT/filename) as c:result.append('-- '+filename+'\n'+';\n'.join(x[0] for x in c.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND type IN ('table','index','view')"))+';')
   return r.app.response_class('\n\n'.join(result),mimetype='text/plain')
  if name=='bundle.zip':
   import zipfile
   b=io.BytesIO()
   with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
    for f in (r.BASE_DIR.parent/'schemas').rglob('*'):
     if f.is_file():z.writestr(f.relative_to(r.BASE_DIR.parent/'schemas').as_posix(),f.read_bytes())
   response=r.app.make_response(b.getvalue());response.mimetype='application/zip';response.headers['Content-Disposition']='attachment; filename=KarnatakaDBT-schemas.zip';return response
  return send_from_directory(r.BASE_DIR.parent/'schemas',name)
 @r.app.get('/schema-catalogue')
 def catalogue():
  r.require_user()
  if g.session.get('mode')!='staff':abort(403)
  data=json.loads((r.BASE_DIR.parent/'schemas/reference/schema-catalog.json').read_text(encoding='utf-8'))
  selected=request.args.get('database','');query=request.args.get('q','').strip().lower()
  databases=[d for d in data['databases'] if not selected or d['id']==selected]
  entries=[]
  for d in databases:
   for relation in d.get('relations',[]):
    if query and query not in (relation['name']+' '+d['database']).lower():continue
    entries.append({'database':d['database'],'name':relation['name'],'kind':relation['type'],'columns':[c for c in d.get('columns',[]) if c.get('table')==relation['name'] or c.get('table_name')==relation['name']],'ddl':d.get('ddl_file')})
  return r.page('schema-catalogue.html',data=data,entries=entries,selected=selected,query=query)
 @r.app.get('/api/registry/export.csv')
 def export():
  r.require_staff();b=io.StringIO();w=csv.writer(b);w.writerow(['reference','household','district','division','members','status','synthetic'])
  for p in r.rows('SELECT * FROM profiles'):
   d=json.loads(p['data']);w.writerow([p['household_ref'],d['household_name'],d['state_name'],d['geography']['zone_name'],len(d['members']),p['status'],True])
  response=r.app.make_response(b.getvalue());response.mimetype='text/csv';response.headers['Content-Disposition']='attachment; filename=KarnatakaDBT-households.csv';return response
 @r.app.get('/automation')
 def automation():r.require_staff();return r.page('automation.html')
 @r.app.post('/automation/run')
 def automation_run():
  r.require_staff()
  if g.session.get('role')!='supervisor':abort(403,'Automation execution requires the supervisor demo role.')
  synced=0
  with r.LOCK:
   for p in r.rows("SELECT * FROM profiles WHERE status='approved' AND sync_status!='complete'"):r.sync_profile(p['sub']);synced+=1
   r.analytics_snapshot();r.audit('automation_cycle',json.dumps({'synchronised':synced,'snapshots_refreshed':True}))
  return r.page('message.html',title='Automation cycle complete',message=f'{synced} approved synthetic households synchronised. Analytics snapshot refreshed. Independent review queues remain available.',back='/services/automation')
 # Refresh source cards from actual current synthetic records, never copied numbers.
 @r.app.before_request
 def sources():
  if request.path not in [r.PREFIX+'/analytics',r.PREFIX+'/api/analytics']:return
  totals={'registry':[{'label':'Synthetic households','value':r.one('SELECT count(*) n FROM profiles')['n']},{'label':'Synthetic individuals','value':sum(len(json.loads(x['data'])['members']) for x in r.rows('SELECT data FROM profiles'))}],'programmes':[{'label':'Active demonstration programmes','value':r.one('SELECT count(*) n FROM programs')['n']},{'label':'Enrolled synthetic applications','value':r.one("SELECT count(*) n FROM applications WHERE status='enrolled'")['n']}]}
  now=r.stamp()
  for name,data in totals.items():r.execute('INSERT OR REPLACE INTO analytics_source_cache VALUES(?,?,?,?,NULL)',('KarnatakaDBT '+name,now,json.dumps({'synthetic_counts':data}),now))
