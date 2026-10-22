"""Authenticated UI and API for the connected departmental register model."""
import json
import secrets
from flask import Blueprint, abort, g, request, redirect
from register_model import RegisterModel, ModelError
from register_contracts import VERSION, SOURCES, SCENARIOS, STAGES, XML_MAPPINGS, PUBLIC_STANDARDS

def install(r):
    model=RegisterModel(r.ROOT)
    r.external_register_model=model
    bp=Blueprint('external_registers',__name__)
    prefix=r.PREFIX

    def require():
        r.require_user()
        if g.session.get('mode')!='staff' or not (g.staff or {'kdbt-programme-supervisor','iqs-programme-supervisor'} & set(g.user.get('roles',[]))):
            abort(403,'Register simulation requires a staff reviewer or programme supervisor.')

    def seeded():
        # Explicit version marker prevents reading/seeding thousands of rows per request.
        with model.connect() as c: ready=c.execute("SELECT 1 FROM meta WHERE key='schema_version'").fetchone()
        if not ready: refresh()

    def refresh():
        catalogue=json.loads((r.ROOT/'karnataka-geography.json').read_text(encoding='utf-8')) if (r.ROOT/'karnataka-geography.json').exists() else r.CATALOGUE
        model.seed(r.rows('SELECT * FROM profiles ORDER BY household_ref'),catalogue['districts'])

    @bp.errorhandler(ModelError)
    def model_error(e):
        if '/api/' in request.path: return {'error':e.message},e.status
        return r.page('message.html',title='Simulation action needs attention',message=e.message,back=prefix+'/register-lab'),e.status

    @bp.get(prefix+'/register-lab')
    def console():
        if not g.user:return redirect(prefix+'/login?mode=staff&register_lab=1')
        require();seeded()
        hh=request.args.get('household','');households=model.households()
        if hh and hh not in {x['reference'] for x in households}:abort(404)
        return r.page('register-lab.html',catalogue=model.catalogue(),households=households,schemes=model.schemes(),runs=model.recent(),scenarios=SCENARIOS,selected=hh,key=secrets.token_urlsafe(24),stages=STAGES)

    @bp.get(prefix+'/register-lab/run/<rid>')
    def journey(rid):
        require();seeded()
        run=model.get(rid)
        return r.page('register-run.html',run=run,stages=STAGES,scenarios=SCENARIOS,scheme=next(x for x in model.schemes() if x['scheme_id']==run['scheme_id']))

    @bp.get(prefix+'/register-lab/source/<source>')
    def source_view(source):
        require();seeded()
        if source not in SOURCES:abort(404)
        hh=request.args.get('household','')
        if hh and hh not in {x['reference'] for x in model.households()}:abort(404)
        info=next(x for x in model.catalogue() if x['id']==source)
        return r.page('register-source.html',info=info,household=hh,records=model.source_records(source,hh) if hh else {},xml_mappings=XML_MAPPINGS if source=='documents' else {})

    @bp.get(prefix+'/api/register-lab/catalogue')
    def catalogue():
        require();seeded()
        return {'version':VERSION,'synthetic':True,'production_schema':False,'sources':model.catalogue(),'document_xml_mappings':XML_MAPPINGS,'public_standards':PUBLIC_STANDARDS,'pending_department_confirmation':['Actual API schema and authentication','Field types and official code lists','Identifier matching rules','Permitted fields and purpose','Refresh frequency and service limits','Payment callback signature and reconciliation contract']}

    @bp.get(prefix+'/api/register-lab/source/<source>')
    def lookup(source):
        require();seeded()
        if source not in SOURCES:abort(404)
        hh=request.args.get('household','')
        if not hh or hh not in {x['reference'] for x in model.households()}:abort(404,'Choose an existing synthetic household.')
        return {'contract_version':VERSION,'source':source,'synthetic':True,'data':model.source_records(source,hh)}

    @bp.post(prefix+'/api/register-lab/runs')
    def create():
        require();seeded()
        rid=model.create(request.form.get('household',''),request.form.get('scheme',''),request.form.get('scenario','normal'),request.form.get('request_key',''),g.user['sub'],request.form.get('cycle','training-2026-10'))
        r.audit('external_register_simulation_created',rid)
        if request.form.get('console'):return redirect(prefix+'/register-lab/run/'+rid)
        return model.get(rid),201

    @bp.get(prefix+'/api/register-lab/runs/<rid>')
    def get_run(rid):require();seeded();return model.get(rid)

    @bp.post(prefix+'/api/register-lab/runs/<rid>/<action>')
    def advance(rid,action):
        require();seeded()
        if action=='replay':result=model.replay_callback(rid,g.user['sub'])
        elif action in {'advance','approve','return','retry'}:result=model.advance(rid,request.form.get('version',''),g.user['sub'],action)
        else:abort(404)
        r.audit('external_register_simulation_'+action,rid)
        if request.form.get('console'):return redirect(prefix+'/register-lab/run/'+rid)
        return result

    @bp.post(prefix+'/api/register-lab/refresh')
    def seed_new():
        require();refresh();r.audit('external_register_seed_new','synthetic profiles only')
        return redirect(prefix+'/register-lab') if request.form.get('console') else {'seeded':True,'overwrites_existing_sources':False}

    @bp.post(prefix+'/api/register-lab/source-income')
    def change_income():
        require();seeded()
        if request.form.get('confirmation')!='UPDATE SYNTHETIC SOURCES':abort(400,'Confirm UPDATE SYNTHETIC SOURCES.')
        try:income=int(request.form.get('monthly_income',''))
        except ValueError:abort(400,'Enter a whole monthly income.')
        result=model.change_income(request.form.get('household',''),income,g.user['sub'])
        r.audit('external_register_source_corrected',request.form.get('household',''))
        return redirect(prefix+'/register-lab/source/revenue?household='+request.form.get('household','')) if request.form.get('console') else result

    @bp.get(prefix+'/api/register-lab/bundle.zip')
    def bundle():
        require();seeded()
        response=r.app.make_response(model.bundle());response.mimetype='application/zip'
        response.headers['Content-Disposition']='attachment; filename=KarnatakaDBT-register-model.zip'
        return response

    @bp.get(prefix+'/api/register-lab/openapi.json')
    def openapi():
        require();seeded()
        def response(description,code='200',schema=None):return {code:{'description':description,'content':{'application/json':{'schema':schema or {'type':'object'}}}}}
        paths={}
        paths[prefix+'/api/register-lab/catalogue']={'get':{'summary':'Versioned source SQL, columns, constraints and provenance','responses':response('Catalogue')}}
        paths[prefix+'/api/register-lab/source/{source}']={'get':{'summary':'Read synthetic departmental records','parameters':[{'name':'source','in':'path','required':True,'schema':{'type':'string','enum':list(SOURCES)}},{'name':'household','in':'query','required':True,'schema':{'type':'string'}}],'responses':response('Source data')}}
        paths[prefix+'/api/register-lab/runs']={'post':{'summary':'Create simulation case with idempotency key','requestBody':{'required':True,'content':{'application/x-www-form-urlencoded':{'schema':{'type':'object','required':['csrf','household','scheme','request_key','cycle'],'properties':{k:{'type':'string'} for k in ['csrf','household','scheme','scenario','request_key','cycle']}}}}},'responses':response('Created or existing case','201')}}
        paths[prefix+'/api/register-lab/runs/{run_id}']={'get':{'parameters':[{'name':'run_id','in':'path','required':True,'schema':{'type':'string'}}],'responses':response('Run with evidence and event timeline')}}
        paths[prefix+'/api/register-lab/runs/{run_id}/{action}']={'post':{'summary':'Advance exactly one stage or replay callback','parameters':[{'name':'run_id','in':'path','required':True,'schema':{'type':'string'}},{'name':'action','in':'path','required':True,'schema':{'type':'string','enum':['advance','approve','return','retry','replay']}}],'requestBody':{'required':True,'content':{'application/x-www-form-urlencoded':{'schema':{'type':'object','required':['csrf','version'],'properties':{'csrf':{'type':'string'},'version':{'type':'integer'}}}}}},'responses':response('Updated run')}}
        components={}
        for entry in model.catalogue():
            for table in entry['tables']:
                components[entry['id']+'_'+table['name']]={'type':'object','description':entry['classification'],'properties':{col['name']:{'type':'integer' if 'INT' in col['type'] else 'number' if col['type']=='REAL' else 'string','nullable':not bool(col['notnull'] or col['pk'])} for col in table['columns']},'required':[col['name'] for col in table['columns'] if col['notnull'] or col['pk']]}
            components[entry['id']+'_response']={'type':'object','required':['contract_version','source','synthetic','data'],'properties':{'contract_version':{'type':'string','enum':[VERSION]},'source':{'type':'string','enum':[entry['id']]},'synthetic':{'type':'boolean','enum':[True]},'data':{'type':'object','properties':{t['name']:{'type':'array','items':{'$ref':'#/components/schemas/'+entry['id']+'_'+t['name']}} for t in entry['tables']}}}}
        paths[prefix+'/api/register-lab/source/{source}']['get']['responses']=response('Synthetic source response',schema={'oneOf':[{'$ref':'#/components/schemas/'+s+'_response'} for s in SOURCES]})
        return {'openapi':'3.0.3','info':{'title':'KarnatakaDBT local register simulation API','version':VERSION,'description':'Simulation contracts only. Staff session cookie and CSRF form value required. Not a government API.'},'paths':paths,'components':{'schemas':components,'securitySchemes':{'staffSession':{'type':'apiKey','in':'cookie','name':'KA-INTAKE' if hasattr(r,'CONFIG') else 'KDBT-DEMO'}}},'security':[{'staffSession':[]}]}

    r.app.register_blueprint(bp)
