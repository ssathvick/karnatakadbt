"""Persona UI for existing sandbox records. Fictional walkthrough stays in the browser."""
import json,math
import karnataka_geography
from flask import Blueprint,request,abort,g,render_template

def install(r):
 bp=Blueprint('persona_workspaces',__name__)
 def personas():
  if not g.user:return []
  if g.session.get('mode')=='beneficiary':return ['citizen']
  rolemap={'officer':'iqs-registration-officer','verifier':'iqs-verification-officer','supervisor':'iqs-programme-supervisor'}
  available=[p for p,role in rolemap.items() if g.staff or role in g.user.get('roles',[])]
  preferred=g.session.get('role')
  return sorted(available,key=lambda p:0 if p==preferred else 1)
 def require(persona=None):
  r.require_user();allowed=personas()
  if not allowed or (persona and persona not in allowed):abort(403,'This workspace is not assigned to your account.')
  return allowed
 def serialize(p):
  d=json.loads(p['data'])
  return {'sub':p['sub'],'reference':p['household_ref'],'name':d['household_name'],'state':d['state_name'],'community':d['community'],'income':d['monthly_income'],'members':[{k:m[k] for k in ['given','family','birth_date','gender']} for m in d['members']], 'status':p['status'],'sync':p['sync_status'],'reason':p['error'],'version':p['updated'],'editable':p['status']=='rejected','self_made':r.is_maker(p,g.user['sub']),'geography':karnataka_geography.geography(d)}
 @bp.get(r.PREFIX+'/workspace')
 def workspace():return render_template('workspace.html',prefix=r.PREFIX)
 @bp.get(r.PREFIX+'/api/workspace')
 def data():
  allowed=require();staff=any(p!='citizen' for p in allowed)
  records=r.rows('SELECT * FROM profiles ORDER BY updated DESC') if staff else r.rows('SELECT * FROM profiles WHERE sub=?',(g.user['sub'],))
  apps=r.rows('SELECT a.*,p.name,r.household_ref FROM applications a JOIN programs p ON p.id=a.program JOIN profiles r ON r.sub=a.sub'+('' if staff else ' WHERE a.sub=?')+' ORDER BY a.id DESC',() if staff else (g.user['sub'],))
  return {'user':{'name':g.user['name']},'personas':allowed,'profiles':[serialize(p) for p in records],'applications':[{'id':a['id'],'name':a['name'],'reference':a['household_ref'],'status':a['status'],'error':bool(a['error'])} for a in apps],'programmes':[{'id':p['id'],'name':p['name'],'amount':p['amount']} for p in r.rows("SELECT * FROM programs WHERE status='ACTIVE'")],'events':[{'action':e['action'],'reference':e['reference'],'at':e['at']} for e in r.rows('SELECT * FROM audit ORDER BY id DESC LIMIT 12')] if staff else [],'csrf':g.session['csrf'],'scope':'Existing synthetic sandbox reviewer scope' if staff else 'Your household only'}
 @bp.post(r.PREFIX+'/api/workspace/profile/<sub>/<action>')
 def action(sub,action):
  require('officer' if action=='correct' else 'verifier')
  with r.LOCK:
   p=r.one('SELECT * FROM profiles WHERE sub=?',(sub,))
   if not p:abort(404,'Registration not found.')
   if request.form.get('version')!=p['updated']:abort(409,'This record changed. Refresh and review the latest version.')
   if action=='correct':
    if p['status']!='rejected':abort(409,'Only returned registrations can be corrected here.')
    d=json.loads(p['data'])
    try:
     name=r.clean(request.form.get('household_name'));community=r.clean(request.form.get('community'));income=float(request.form.get('income',''))
     if not name or not community or not math.isfinite(income) or not 0<=income<=1e9:raise ValueError()
    except (ValueError,TypeError):abort(400,'Enter a household name, community and valid monthly income.')
    d.update(household_name=name,community=community,monthly_income=income)
    d['geography']=karnataka_geography.geography(d)
    r.execute("UPDATE profiles SET data=?,status='pending_review',error=NULL,last_editor=?,updated=? WHERE sub=?",(json.dumps(d),g.user['sub'],r.stamp(),sub));r.audit('officer_corrected_and_resubmitted',p['household_ref'])
   elif action in ['approve','reject']:
    if p['status']!='pending_review':abort(409,'This registration is not awaiting review.')
    if r.is_maker(p,g.user['sub']):abort(403,'A different reviewer must decide a record you created or corrected.')
    if action=='approve' and request.form.get('checks')!='confirmed':abort(400,'Complete the review checks before approving.')
    g.workspace_verification_authorized=True
    response=r.staff_profile_decision(sub,action)
    if response.status_code>=400:return response
   else:abort(404)
  return {'status':'saved'}
 r.app.register_blueprint(bp)
