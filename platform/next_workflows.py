"""JSON adapters for Next.js forms; retain the existing workflow handlers."""
import datetime
import json
import math
import uuid
from flask import Blueprint, abort, g, request
import karnataka_geography as geo
from register_contracts import SCENARIOS, STAGES
from register_model import ModelError

def install(r):
    bp=Blueprint('next_workflows',__name__)
    prefix=r.PREFIX+'/api/next'

    @bp.errorhandler(ValueError)
    def invalid_value(error):return {'error':str(error) or 'Check the form values.'},400

    @bp.errorhandler(ModelError)
    def invalid_model(error):return {'error':error.message},error.status

    def capabilities():
        roles={x.replace('iqs-','kdbt-') for x in g.user.get('roles',[])}
        staff=g.session.get('mode')=='staff'
        supervisor=staff and ('kdbt-programme-supervisor' in roles or g.session.get('role')=='supervisor')
        verifier=staff and (g.staff or 'kdbt-verification-officer' in roles)
        return {'citizen':g.session.get('mode')=='beneficiary','correct':staff and (g.staff or 'kdbt-registration-officer' in roles),
                'programmes':supervisor,'applications':verifier,'payments':staff and (g.staff or supervisor)}

    def require(cap=None):
        r.require_user()
        if cap and not capabilities().get(cap):abort(403,'This action is not assigned to your account.')

    def invoke(rule,**params):
        endpoint=next(x.endpoint for x in r.app.url_map.iter_rules() if x.rule==rule and 'POST' in x.methods)
        response=r.app.make_response(r.app.view_functions[endpoint](**params))
        if response.status_code>=400:
            if response.is_json:return response
            return {'error':'The backend did not accept this operation. Check the fields and refresh the record before retrying.'},response.status_code
        return {'saved':True}

    def profile(sub):
        require()
        sub=g.user['sub'] if sub=='me' else sub
        if sub!=g.user['sub']:require('correct')
        elif g.session.get('mode')!='beneficiary':require('correct')
        return r.one('SELECT * FROM profiles WHERE sub=?',(sub,)),sub

    @bp.get(prefix+'/workflows')
    def workflows():
        require();caps=capabilities();staff=g.session.get('mode')=='staff'
        programmes=r.rows('SELECT * FROM programs ORDER BY id DESC') if staff else r.rows("SELECT * FROM programs WHERE status='ACTIVE' ORDER BY id DESC")
        if hasattr(r,'backend'):
            from core_store import programmes as core_programmes
            core_records={p['id']:p for p in r.backend.store.rows(core_programmes)}
            versions={pid:p['version'] for pid,p in core_records.items()}
            programmes=[{**p,'core_version':versions.get(p['id']),'rules':core_records.get(p['id'],{}).get('configuration',{}).get('rules',{})} for p in programmes]
        applications=r.rows('SELECT a.*,p.name,h.household_ref FROM applications a JOIN programs p ON p.id=a.program JOIN profiles h ON h.sub=a.sub'+('' if caps['applications'] else ' WHERE a.sub=?')+' ORDER BY a.id DESC',() if caps['applications'] else (g.user['sub'],))
        if hasattr(r,'backend'):
            from core_store import applications as core_applications
            evidence={a['id']:a['eligibility'] for a in r.backend.store.rows(core_applications)}
            applications=[{**a,'eligibility':evidence.get(a['id'])} for a in applications]
        own=r.one('SELECT * FROM profiles WHERE sub=?',(g.user['sub'],)) if caps['citizen'] else None
        return {'capabilities':caps,'csrf':g.session['csrf'],'programmes':programmes,'applications':applications,
                'own_registration':{'status':own['status'],'sync':own['sync_status']} if own else None,
                'districts':geo.CATALOGUE['districts'],'scope':'Current intake programme records; separate from connected-register training schemes.'}

    @bp.get(prefix+'/households/<sub>')
    def household(sub):
        p,sub=profile(sub)
        if not p and sub!=g.user['sub']:abort(404)
        return {'sub':sub,'profile':{'reference':p['household_ref'],'status':p['status'],'version':p['updated'],'data':json.loads(p['data'])} if p else None,
                'districts':geo.CATALOGUE['districts'],'csrf':g.session['csrf'],'citizen':capabilities()['citizen']}

    def validate_household(old):
        form=request.form;district=geo.AREAS.get(form.get('state'))
        if not district:abort(400,'Choose one of Karnataka’s 31 districts.')
        try:
            income=float(form.get('income',''))
            if not math.isfinite(income) or not 0<=income<=1e9:raise ValueError()
        except ValueError:abort(400,'Enter a finite monthly income from 0 to 1,000,000,000 INR.')
        if hasattr(r,'backend'):
            from core_store import minor
            minor(form.get('income',''))
        name=r.clean(form.get('household_name'));community=r.clean(form.get('community'))
        if not name:abort(400,'Enter the household name.')
        if form.get('synthetic')!='1':abort(400,'Confirm that these are fictional household details.')
        members=[]
        try:
            for i in range(8):
                given=r.clean(form.get('given_'+str(i)));family=r.clean(form.get('family_'+str(i)))
                if not given and not family:
                    if any(form.get(k+'_'+str(i)) for k in ['birth','gender']):raise ValueError('Complete or remove the member row.')
                    continue
                birth=datetime.date.fromisoformat(form.get('birth_'+str(i),''));gender=form.get('gender_'+str(i))
                if not given or not family or birth.year<1900 or birth>datetime.date.today() or gender not in ['Female','Male','Other']:raise ValueError('Check member names, date of birth and gender.')
                prior=(old.get('members') or [])
                member_ref=form.get('member_ref_'+str(i))
                if member_ref and member_ref not in {m.get('ref') for m in prior}:raise ValueError('Member identity changed. Reload the household.')
                if member_ref and member_ref in {m['ref'] for m in members}:raise ValueError('A member cannot appear twice.')
                members.append({'given':given,'family':family,'birth_date':str(birth),'gender':gender,'ref':member_ref or 'KA-I-'+uuid.uuid4().hex[:16]})
            if not members:raise ValueError('Add at least one household member.')
            extra=[k for k in form if k.startswith(('given_','family_','birth_','gender_')) and (not k.rsplit('_',1)[-1].isdigit() or int(k.rsplit('_',1)[-1])>=8)]
            if extra:raise ValueError('A household supports at most eight members.')
            data={**old,'household_name':name,'community':community,'monthly_income':income,'state':district['id'],'state_name':district['name'],'district_id':district['id'],'district_name':district['name'],'country_code':'IND','state_code':'IN-KA','members':members,'synthetic':True}
            data['geography']=geo.capture(form,data)
        except (ValueError,TypeError) as e:abort(400,str(e) or 'Check household fields.')
        return data

    @bp.post(prefix+'/households/<sub>')
    def save_household(sub):
        with r.LOCK:
            p,sub=profile(sub)
            if request.form.get('version','')!=(p['updated'] if p else ''):abort(409,'This household changed. Reload before saving.')
            citizen=capabilities()['citizen'] and sub==g.user['sub']
            if p and p['status']=='approved':abort(409,'Approved household details are locked. Coordinates can be updated separately.')
            if not citizen and (not p or p['status']!='rejected'):abort(409,'Staff may correct only returned registrations.')
            data=validate_household(json.loads(p['data']) if p else {})
            if citizen:
                # The native handler retains identifier creation and backend-specific
                # persistence. Validation above also rejects non-finite amounts.
                return invoke(r.PREFIX+'/profile')
            with r.db() as connection:
                changed=connection.execute("UPDATE profiles SET data=?,ref=?,status='pending_review',sync_status='not_started',error=NULL,last_editor=?,updated=? WHERE sub=? AND updated=?",(json.dumps(data),data['members'][0]['ref'],g.user['sub'],r.stamp(),sub,p['updated'])).rowcount
                if not changed:abort(409,'This household changed. Reload before saving.')
            r.audit('officer_corrected_and_resubmitted',p['household_ref'])
            return {'saved':True}

    @bp.post(prefix+'/programmes')
    def create_programme():
        require('programmes')
        try:
            amount=float(request.form.get('amount',''));income=float(request.form.get('max_income',''));minimum=int(request.form.get('min_members',''))
            mnemonic=request.form.get('mnemonic','')
            if not math.isfinite(amount) or not math.isfinite(income) or not 0<amount<=1e6 or not 0<=income<=1e9 or not 1<=minimum<=8 or not mnemonic.replace('_','').isalnum() or len(mnemonic)>30 or not r.clean(request.form.get('name')):raise ValueError()
        except ValueError:abort(400,'Check programme name, unique mnemonic, benefit amount, income ceiling and household size.')
        from programme_rules import validate_rules
        rules=validate_rules(request.form.get('rules') or None,minimum)
        if rules and not hasattr(r,'backend'):abort(409,'Additional rules require the independent backend.')
        return invoke(r.PREFIX+'/staff/program')

    @bp.post(prefix+'/programmes/<int:pid>/apply')
    def apply(pid):
        require('citizen')
        return invoke(r.PREFIX+'/apply/<int:pid>',pid=pid)

    @bp.post(prefix+'/programmes/<int:pid>')
    def update_programme(pid):
        require('programmes')
        if not hasattr(r,'backend'):abort(409,'Programme editing requires the independent core backend.')
        from core_store import DomainConflict
        try:
            r.backend.update_programme(pid,int(request.form.get('version','')),r.clean(request.form.get('name')),request.form.get('amount'),request.form.get('max_income'),int(request.form.get('min_members','')),request.form.get('status'),request.form.get('rules') or None)
        except DomainConflict as e:abort(409,str(e))
        except (ValueError,TypeError) as e:abort(400,str(e))
        r.audit('programme_configuration_updated',pid)
        return {'saved':True}

    @bp.post(prefix+'/applications/<int:aid>/<action>')
    def decide(aid,action):
        require('applications')
        if action not in ['check','enroll','reject']:abort(404)
        with r.LOCK:
            a=r.one('SELECT * FROM applications WHERE id=?',(aid,))
            if not a:abort(404)
            if request.form.get('expected_status')!=a['status']:abort(409,'Application status changed. Refresh before continuing.')
            return invoke(r.PREFIX+'/staff/application/<int:aid>/<action>',aid=aid,action=action)

    @bp.post(prefix+'/households/<sub>/retry')
    def retry_sync(sub):
        require('applications')
        with r.LOCK:
            p=r.one('SELECT * FROM profiles WHERE sub=?',(sub,))
            if not p:abort(404)
            if request.form.get('version')!=p['updated']:abort(409,'Household changed. Refresh before retrying.')
            if p['status']!='approved' or p['sync_status']=='complete':abort(409,'Only approved households with pending synchronization can be retried.')
            return invoke(r.PREFIX+'/staff/profile/<sub>/<action>',sub=sub,action='retry')

    @bp.get(prefix+'/journeys')
    def journeys():
        require('payments');model=r.external_register_model
        with model.connect() as c:ready=c.execute("SELECT 1 FROM meta WHERE key='schema_version'").fetchone()
        if not ready:model.seed(r.rows('SELECT * FROM profiles ORDER BY household_ref'),geo.CATALOGUE['districts'])
        return {'households':model.households(),'schemes':model.schemes(),'runs':model.recent(),'stages':STAGES,'scenarios':SCENARIOS,'csrf':g.session['csrf'],
                'scope':'Connected-register training cases. Instructions, callbacks and amounts are synthetic; no real transfer is sent. The most recent 100 cases are shown.'}

    @bp.get(prefix+'/journeys/<rid>/ledger')
    def ledger(rid):
        require('payments');model=r.external_register_model
        with model.connect(attached=True) as c:
            c.execute('BEGIN')
            run=c.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
            if not run:abort(404)
            queries={
                'sanctions':('SELECT * FROM schemes.sanctions WHERE run_id=?',(rid,)),
                'funding':('SELECT * FROM treasury.reservations WHERE run_id=?',(rid,)),
                'instructions':('SELECT * FROM bank.instructions WHERE run_id=?',(rid,)),
                'settlements':('SELECT s.* FROM bank.settlements s JOIN bank.instructions i USING(instruction_id) WHERE i.run_id=?',(rid,)),
                'notifications':('SELECT * FROM notifications.deliveries WHERE run_id=?',(rid,)),
                'exceptions':('SELECT * FROM notifications.grievances WHERE run_id=?',(rid,)),
            }
            return {'run_id':rid,'version':run['version'],'synthetic':True,**{name:[dict(row) for row in c.execute(sql,args)] for name,(sql,args) in queries.items()}}

    r.app.register_blueprint(bp)
