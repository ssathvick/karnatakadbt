"""Persistent departmental register laboratory. All external services are local.

Source reads use named, replaceable adapters. Mutable simulation ledgers use
attached SQLite databases in rollback-journal mode for atomic multi-file commits.
Native registration/PBMS records are read as seed snapshots, never changed here.
"""
import contextlib
import datetime as dt
import hashlib
import io
import json
import math
import sqlite3
import threading
import tempfile
import uuid
import zipfile
from pathlib import Path
from register_contracts import DDL, SOURCES, VERSION, ORCHESTRATOR_DDL, STAGES, SCENARIOS, XML_MAPPINGS, PUBLIC_STANDARDS

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def dump(value): return json.dumps(value, ensure_ascii=False, sort_keys=True)

class ModelError(Exception):
    def __init__(self, message, status=409): self.message, self.status = message, status

class RegisterModel:
    def __init__(self, root):
        self.root = Path(root) / 'external-registers'
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as c: c.executescript(ORCHESTRATOR_DDL)

    @contextlib.contextmanager
    def connect(self, attached=False):
        c = sqlite3.connect(self.root/'orchestration.sqlite', timeout=30)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        # Atomic commits across attached databases require DELETE journalling.
        c.execute('PRAGMA journal_mode=DELETE')
        if attached:
            for source in ['schemes','treasury','bank','notifications']:
                c.execute('ATTACH DATABASE ? AS '+source, (str(self.root/(source+'.sqlite')),))
        try:
            with c: yield c
        finally: c.close()

    @contextlib.contextmanager
    def source_db(self, source):
        if source not in SOURCES: raise ModelError('Unknown source.',404)
        c = sqlite3.connect(self.root/(source+'.sqlite'),timeout=30)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            with c: yield c
        finally: c.close()

    def seed(self, profiles, districts):
        """Incremental, non-destructive import of fictional profiles; no overwrite."""
        with self.lock:
            for source in SOURCES:
                with self.source_db(source) as c:
                    existing=c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='source_meta'").fetchone()
                    if not existing:
                        c.executescript(DDL[source])
                        c.execute('CREATE TABLE source_meta(version TEXT NOT NULL, classification TEXT NOT NULL, synthetic INTEGER NOT NULL CHECK(synthetic=1))')
                        c.execute('INSERT INTO source_meta VALUES(?,?,1)',(VERSION,SOURCES[source][3]))
            with self.source_db('geography') as c:
                for d in districts:
                    c.execute('INSERT OR IGNORE INTO districts VALUES(?,?,?,?,?)',(d['id'],d['name'],d['division'],None,'synthetic_project_code'))
            definitions = [
              ('SIM-HOUSEHOLD','Household support demonstration','household',25000,200000,['kutumba','ahara','revenue','ejanma','identity','documents','geography','sevasindhu']),
              ('SIM-FARMER','Farmer support demonstration','farmer',30000,200000,['kutumba','revenue','fruits','bhoomi','ejanma','identity','documents','geography','sevasindhu']),
              ('SIM-STUDENT','Student scholarship demonstration','student',22000,150000,['kutumba','revenue','education','ejanma','identity','documents','geography','sevasindhu']),
            ]
            with self.source_db('schemes') as c:
                for sid,name,audience,limit,amount,required in definitions:
                    c.execute('INSERT OR IGNORE INTO schemes VALUES(?,?,?,?,?,?,?,?)',(sid,name,'demo-2026.1',audience,limit,amount,'INR',dump(required)))
            with self.source_db('treasury') as c:
                for sid,*_ in definitions: c.execute('INSERT OR IGNORE INTO budgets VALUES(?,?,?)',(sid,1000000000,'INR'))
            today=dt.date.today(); at=now()
            # Open each file once during seeding; connect() always closes handles.
            with contextlib.ExitStack() as stack:
                conns={s:stack.enter_context(self.source_db(s)) for s in SOURCES}
                main=stack.enter_context(self.connect())
                for index,p in enumerate(profiles,1):
                    data=json.loads(p['data'])
                    if data.get('synthetic') is not True or not data.get('members'): continue
                    hh=p['household_ref']
                    if main.execute('SELECT 1 FROM crosswalk WHERE household_ref=?',(hh,)).fetchone(): continue
                    family='SIM-FAM-'+hashlib.sha256(hh.encode()).hexdigest()[:12]
                    district=data.get('district_id') or data.get('state')
                    if not conns['geography'].execute('SELECT 1 FROM districts WHERE district_id=?',(district,)).fetchone(): continue
                    members=[]
                    for i,m in enumerate(data['members']):
                        person='SIM-PER-'+hashlib.sha256((hh+':'+str(i)).encode()).hexdigest()[:14]
                        token='SIM-ID-'+hashlib.sha256(person.encode()).hexdigest()[:16]
                        members.append((person,token,m))
                    income=int(round(float(data['monthly_income'])))
                    conns['kutumba'].execute('INSERT INTO families VALUES(?,?,?,?,?,?,?,?)',(family,hh,data['household_name'],district,'Synthetic address in '+data.get('district_name',data.get('state_name','Karnataka')),income,'active',at))
                    for i,(person,token,m) in enumerate(members):
                        conns['kutumba'].execute('INSERT INTO members VALUES(?,?,?,?,?,?,?,?,?,?)',(person,family,m.get('ref',person),m['given'],m['family'],m['birth_date'],m['gender'],'self' if i==0 else 'child',token,at))
                        conns['identity'].execute('INSERT INTO verifications VALUES(?,?,?,?,?,?,?)',(token,hh,person,m['given']+' '+m['family'],m['birth_date'],'verified',at))
                        conns['ejanma'].execute('INSERT INTO life_events VALUES(?,?,?,?,?,?,?)',('SIM-EVENT-'+person,hh,person,m['birth_date'],None,'registered',at))
                        if i>0:
                            conns['education'].execute('INSERT INTO students VALUES(?,?,?,?,?,?,?,?,?)',('SIM-STUDENT-'+person,hh,person,'SIM-SCHOOL-'+district,'2026-27','School education','active','none',at))
                    head,_,head_data=members[0]
                    card='SIM-CARD-'+family
                    conns['ahara'].execute('INSERT INTO ration_cards VALUES(?,?,?,?,?,?,?)',(card,hh,family,['PHH','AAY','NPHH'][(index-1)%3],'active',district,at))
                    for person,_,_ in members: conns['ahara'].execute('INSERT INTO card_members VALUES(?,?)',(card,person))
                    for kind in ['income','residence']:
                        cert='SIM-CERT-'+kind+'-'+family
                        conns['revenue'].execute('INSERT INTO certificates VALUES(?,?,?,?,?,?,?,?,?)',(cert,hh,head,kind,income*12 if kind=='income' else None,str(today-dt.timedelta(days=30)),str(today+dt.timedelta(days=365)),'active',at))
                        conns['documents'].execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',('SIM-DOC-'+cert,hh,head,cert,kind,'Simulated Karnataka Revenue issuer',head_data['given']+' '+head_data['family'],str(today-dt.timedelta(days=30)),str(today+dt.timedelta(days=365)),'A','unsigned_simulation',at))
                    village='SIM-VILLAGE-'+district+'-'+str((index-1)%40+1)
                    if index%3!=0:
                        farmer='SIM-FARMER-'+family; parcel='SIM-PARCEL-'+family
                        conns['fruits'].execute('INSERT INTO farmers VALUES(?,?,?,?,?,?)',(farmer,hh,head,family,'active',at))
                        conns['fruits'].execute('INSERT INTO crops VALUES(?,?,?,?,?,?)',('SIM-CROP-'+family,farmer,parcel,'Kharif 2026',['Ragi','Rice','Maize','Jowar'][index%4],round(.4+(index%20)/10,2)))
                        conns['bhoomi'].execute('INSERT INTO parcels VALUES(?,?,?,?,?,?,?,?,?)',(parcel,hh,district,village,'SIM-SURVEY-'+str(index),round(.4+(index%20)/10,2),head,'clear',at))
                    conns['sevasindhu'].execute('INSERT INTO service_applications VALUES(?,?,?,?,?)',('SIM-SERVICE-'+family,hh,'SIM-DBT-INTAKE','approved',at))
                    geo=data.get('geography',{});lat,lon=geo.get('latitude'),geo.get('longitude')
                    conns['geography'].execute('INSERT INTO locations VALUES(?,?,?,?,?,?,?,?)',('SIM-LOC-'+family,hh,district,village,lat,lon,geo.get('coordinate_source','not_captured'),0))
                    conns['bank'].execute('INSERT INTO accounts VALUES(?,?,?,?,?,?)',('SIM-ACCOUNT-'+family,hh,head,'valid','SIMULATED',at))
                    snapshot={'household_ref':hh,'data':data,'platform_status':p['status'],'platform_sync':p['sync_status'],'family_id':family,'head_person_id':head,'member_ids':[x[0] for x in members]}
                    main.execute('INSERT INTO crosswalk VALUES(?,?,?,?)',(hh,family,dump(snapshot),p.get('updated','seed')))
                main.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('schema_version',VERSION))
                main.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('last_seed',at))

    def households(self):
        with self.connect() as c:
            result=[]
            for x in c.execute('SELECT * FROM crosswalk ORDER BY household_ref'):
                s=json.loads(x['snapshot']);d=s['data']
                result.append({'reference':x['household_ref'],'name':d['household_name'],'district':d.get('district_name',d.get('state_name')),'district_id':d.get('district_id',d.get('state')),'income':d['monthly_income'],'platform_status':s['platform_status']})
            return result

    def schemes(self):
        with self.source_db('schemes') as c: return [dict(x) for x in c.execute('SELECT * FROM schemes')]

    def source_records(self, source, hh):
        """Adapter returns real rows from the selected local source database."""
        with self.source_db(source) as c:
            queries={
              'kutumba':[('families','SELECT * FROM families WHERE household_ref=?'),('members','SELECT m.* FROM members m JOIN families f USING(family_id) WHERE f.household_ref=?')],
              'ahara':[('ration_cards','SELECT * FROM ration_cards WHERE household_ref=?'),('card_members','SELECT m.* FROM card_members m JOIN ration_cards r USING(card_id) WHERE r.household_ref=?')],
              'revenue':[('certificates','SELECT * FROM certificates WHERE household_ref=?')],
              'fruits':[('farmers','SELECT * FROM farmers WHERE household_ref=?'),('crops','SELECT c.* FROM crops c JOIN farmers f USING(farmer_id) WHERE f.household_ref=?')],
              'bhoomi':[('parcels','SELECT * FROM parcels WHERE household_ref=?')],
              'ejanma':[('life_events','SELECT * FROM life_events WHERE household_ref=?')],
              'education':[('students','SELECT * FROM students WHERE household_ref=?')],
              'sevasindhu':[('service_applications','SELECT * FROM service_applications WHERE household_ref=?')],
              'geography':[('districts','SELECT d.* FROM districts d JOIN locations l USING(district_id) WHERE l.household_ref=?'),('locations','SELECT * FROM locations WHERE household_ref=?')],
              'identity':[('verifications','SELECT * FROM verifications WHERE household_ref=?')],
              'documents':[('documents','SELECT * FROM documents WHERE household_ref=?')],
              'schemes':[('sanctions','SELECT * FROM sanctions WHERE household_ref=?')],
              'bank':[('accounts','SELECT * FROM accounts WHERE household_ref=?'),('instructions','SELECT i.* FROM instructions i JOIN accounts a USING(account_token) WHERE a.household_ref=?'),('settlements','SELECT s.* FROM settlements s JOIN instructions i USING(instruction_id) JOIN accounts a USING(account_token) WHERE a.household_ref=?')],
              'notifications':[('deliveries','SELECT * FROM deliveries WHERE household_ref=?'),('grievances','SELECT * FROM grievances WHERE household_ref=?')],
            }
            if source=='treasury':
                with self.connect() as main:ids=[x[0] for x in main.execute('SELECT id FROM runs WHERE household_ref=?',(hh,))]
                return {'budgets':[dict(x) for x in c.execute('SELECT * FROM budgets')],'reservations':[dict(x) for x in c.execute('SELECT * FROM reservations WHERE run_id IN ('+','.join('?' for _ in ids)+')',ids)] if ids else []}
            if source=='schemes':return {'schemes':[dict(x) for x in c.execute('SELECT * FROM schemes')],'sanctions':[dict(x) for x in c.execute('SELECT * FROM sanctions WHERE household_ref=?',(hh,))]}
            return {name:[dict(x) for x in c.execute(q,(hh,))] for name,q in queries[source]}

    def catalogue(self):
        result=[]
        for source,(name,owner,url,classification) in SOURCES.items():
            tables=[]
            with self.source_db(source) as c:
                for row in c.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name!='source_meta' ORDER BY name").fetchall():
                    columns=[dict(x) for x in c.execute('PRAGMA table_info('+row['name']+')')]
                    foreign=[dict(x) for x in c.execute('PRAGMA foreign_key_list('+row['name']+')')]
                    tables.append({'name':row['name'],'sql':row['sql'],'columns':columns,'foreign_keys':foreign,'count':c.execute('SELECT count(*) FROM '+row['name']).fetchone()[0]})
            result.append({'id':source,'name':name,'owner':owner,'url':url,'classification':classification,'version':VERSION,'tables':tables,'synthetic':True})
        return result

    def log(self,c,run,stage,source,target,status,request,response,actor,table=None):
        c.execute('INSERT INTO events(run_id,stage,source,target,status,request_json,response_json,source_table,fetched_at,actor,contract_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(run['id'],stage,source,target,status,dump(request),dump(response),table,now(),actor,VERSION))

    def create(self,hh,scheme,scenario,key,actor,cycle):
        if scenario not in SCENARIOS or scheme not in {s['scheme_id'] for s in self.schemes()}: raise ModelError('Choose a valid scheme and scenario.',400)
        if not key or len(key)>100 or not cycle or len(cycle)>50: raise ModelError('Invalid request key or training cycle.',400)
        with self.lock,self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM runs WHERE request_key=?',(key,)).fetchone()
            if old:
                if (old['household_ref'],old['scheme_id'],old['scenario'],old['cycle'])!=(hh,scheme,scenario,cycle): raise ModelError('Request key already belongs to another run.')
                return old['id']
            record=c.execute('SELECT * FROM crosswalk WHERE household_ref=?',(hh,)).fetchone()
            if not record: raise ModelError('Synthetic household not found. Refresh source seeds first.',404)
            if c.execute('SELECT count(*) FROM runs').fetchone()[0]>=10000: raise ModelError('Training run capacity reached.')
            rid=str(uuid.uuid4());at=now()
            c.execute('INSERT INTO runs(id,request_key,household_ref,scheme_id,scenario,cycle,state,snapshot,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(rid,key,hh,scheme,scenario,cycle,'registered',record['snapshot'],actor,at,at))
            run=dict(c.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone())
            self.log(c,run,STAGES[0],'KarnatakaDBT intake','Simulation case','captured',{'household_ref':hh},{'snapshot':json.loads(record['snapshot']),'synthetic':True},actor,'crosswalk')
            return rid

    def get(self,rid):
        with self.connect() as c:
            row=c.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
            if not row: raise ModelError('Training run not found.',404)
            run=dict(row);run['snapshot']=json.loads(run['snapshot'])
            run['events']=[{**dict(x),'request':json.loads(x['request_json']),'response':json.loads(x['response_json'])} for x in c.execute('SELECT * FROM events WHERE run_id=? ORDER BY id',(rid,))]
            run['evidence']=[{**dict(x),'payload':json.loads(x['payload'])} for x in c.execute('SELECT * FROM evidence WHERE run_id=?',(rid,))]
            row=c.execute('SELECT * FROM eligibility WHERE run_id=?',(rid,)).fetchone()
            run['eligibility']={**dict(row),'checks':json.loads(row['checks'])} if row else None
            run['next_stage']=STAGES[run['stage']+1] if run['stage']<len(STAGES)-1 else None
            run['can_advance']=run['state'] not in {'needs_correction','not_eligible','duplicate_benefit','account_invalid','funding_failed','payment_failed','reconciliation_exception','reversed','completed','returned'}
            run['can_retry']=run['state'] in {'source_unavailable','awaiting_settlement'}
            return run

    def recent(self):
        with self.connect() as c: return [dict(x) for x in c.execute('SELECT id,household_ref,scheme_id,scenario,cycle,state,stage,version,created_at FROM runs ORDER BY rowid DESC LIMIT 100')]

    def _fetch(self,c,run,actor,recovered=False):
        scheme=next(s for s in self.schemes() if s['scheme_id']==run['scheme_id'])
        scenario=run['scenario'];overall=[];family_payload=None
        for source in json.loads(scheme['required_sources']):
            payload=self.source_records(source,run['household_ref']);status='verified'
            if source=='kutumba' and scenario=='source_outage' and not recovered: payload={};status='unavailable'
            elif source=='kutumba' and scenario=='no_match': payload={};status='no_match'
            elif source=='identity' and scenario=='identity_mismatch':
                payload['verifications'][0]['status']='mismatch';status='mismatch'
            elif source=='revenue' and scenario=='certificate_expired':
                for cert in payload['certificates']:
                    if cert['certificate_type']=='income':cert['valid_until']='2000-01-01';cert['status']='expired'
                status='expired'
            elif source=='ejanma' and scenario=='deceased':payload['life_events'][0]['death_date']=str(dt.date.today());status='review_required'
            # Validate essential evidence rather than treating a nonempty HTTP result as proof.
            if status=='verified':
                if source=='kutumba':
                    fam=payload.get('families',[]);people=payload.get('members',[])
                    if not fam or not people:status='no_match'
                    elif fam[0]['status']!='active':status='review_required'
                elif source=='revenue':
                    cert=next((x for x in payload['certificates'] if x['certificate_type']=='income'),None)
                    if not cert:status='no_match'
                    elif cert['status']!='active' or cert['valid_until']<str(dt.date.today()):status='expired'
                elif source=='documents' and (not payload['documents'] or any(x['status']!='A' or x['expiry_date']<str(dt.date.today()) for x in payload['documents'])):status='review_required'
                elif source=='identity' and (not payload['verifications'] or any(x['status']!='verified' for x in payload['verifications'])):status='mismatch'
                elif source=='ejanma' and (not payload['life_events'] or any(x['death_date'] or x['registration_status']!='registered' for x in payload['life_events'])):status='review_required'
                elif source=='geography' and not payload['locations']:status='no_match'
                elif source=='ahara' and (not payload['ration_cards'] or payload['ration_cards'][0]['status']!='active'):status='review_required'
                elif source=='sevasindhu' and (not payload['service_applications'] or payload['service_applications'][0]['status']!='approved'):status='review_required'
            if source=='kutumba' and status=='verified':family_payload=payload
            if status=='verified' and family_payload:
                people={p['person_id']:p for p in family_payload['members']}
                family=family_payload['families'][0]
                head=next((p for p in people.values() if p['relationship']=='self'),None)
                if source=='identity':
                    ids=payload['verifications']
                    if {x['person_id'] for x in ids}!=set(people) or any(x['identity_token']!=people[x['person_id']]['identity_token'] or x['name']!=people[x['person_id']]['given_name']+' '+people[x['person_id']]['family_name'] or x['birth_date']!=people[x['person_id']]['birth_date'] for x in ids):status='mismatch'
                elif source=='ejanma':
                    events=payload['life_events']
                    if {x['person_id'] for x in events}!=set(people) or any(x['birth_date']!=people[x['person_id']]['birth_date'] for x in events):status='mismatch'
                elif source=='ahara':
                    if payload['ration_cards'][0]['family_id']!=family['family_id'] or {x['person_id'] for x in payload['card_members']}!=set(people):status='mismatch'
                elif source=='revenue' and any(x['person_id'] not in people for x in payload['certificates']):status='mismatch'
                elif source=='documents' and (not head or any(x['person_id'] not in people or x['holder_name']!=people[x['person_id']]['given_name']+' '+people[x['person_id']]['family_name'] for x in payload['documents'])):status='mismatch'
                elif source=='geography' and payload['locations'][0]['district_id']!=family['district_id']:status='mismatch'
            overall.append(status)
            self.log(c,run,STAGES[1],SOURCES[source][0],'Evidence store',status,{'household_ref':run['household_ref'],'purpose':'synthetic '+scheme['audience']+' eligibility'}, {'data':payload,'scenario_override':scenario!='normal','synthetic':True},actor,','.join(payload))
            c.execute('INSERT OR REPLACE INTO evidence VALUES(?,?,?,?,?)',(run['id'],source,status,dump(payload),now()))
        return 'source_unavailable' if 'unavailable' in overall else 'evidence_ready' if all(x=='verified' for x in overall) else 'needs_correction'

    def _case(self,c,run,reason):
        c.execute('INSERT OR IGNORE INTO notifications.grievances VALUES(?,?,?,?,?,?)',('SIM-CASE-'+run['id'],run['id'],run['household_ref'],reason,'open',now()))

    def advance(self,rid,version,actor,action='advance'):
        with self.lock,self.connect(attached=True) as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
            if not row:raise ModelError('Training run not found.',404)
            run=dict(row)
            if str(run['version'])!=str(version):raise ModelError('This run changed. Refresh before continuing.')
            state=run['state'];stage=run['stage'];scenario=run['scenario'];snapshot=json.loads(run['snapshot'])
            scheme=dict(c.execute('SELECT * FROM schemes.schemes WHERE scheme_id=?',(run['scheme_id'],)).fetchone())
            amount=scheme['benefit_minor'];error=None;response={};source='KarnatakaDBT';target='Simulation ledger'
            if action=='return':
                if state!='evidence_ready':raise ModelError('Only an evidence-ready case can be returned.')
                state='returned';error='Reviewer returned the simulation case for correction.'
            elif state=='source_unavailable':
                if action!='retry':raise ModelError('Use Retry after simulated source recovery.')
                state=self._fetch(c,run,actor,recovered=True);stage=1
            elif state=='awaiting_settlement':
                if action!='retry':raise ModelError('Use Retry to deliver the delayed simulated callback.')
                stage=9;state,response=self._settle(c,run,amount);source='Bank callback';target='Callback inbox'
            else:
                if action not in {'advance','approve'}:raise ModelError('Action is not available.')
                if state in {'needs_correction','not_eligible','duplicate_benefit','account_invalid','funding_failed','payment_failed','reconciliation_exception','reversed','completed','returned'}:raise ModelError('Resolve the source or exception and start a new training run.')
                stage+=1
                if stage in (2,5) and action!='approve':raise ModelError('This stage requires an explicit reviewer approval.')
                if stage not in (2,5) and action=='approve':raise ModelError('Approval is not available at this stage.')
                if stage==1:state=self._fetch(c,run,actor)
                elif stage==2:
                    state='review_approved';response={'reviewer':actor,'decision':'approved','scope':'simulation only'}
                elif stage==3:
                    evidence={x['source']:json.loads(x['payload']) for x in c.execute('SELECT * FROM evidence WHERE run_id=?',(rid,))}
                    data=evidence['kutumba'];c.execute('INSERT INTO mirror_households VALUES(?,?,?,?)',(rid,run['household_ref'],dump(data),now()))
                    state='synchronized';source='Evidence store';target='Simulation household registry';response={'family_id':data['families'][0]['family_id'],'member_count':len(data['members']),'native_registry_write':False}
                elif stage==4:
                    e={x['source']:json.loads(x['payload']) for x in c.execute('SELECT * FROM evidence WHERE run_id=?',(rid,))}
                    cert=next(x for x in e['revenue']['certificates'] if x['certificate_type']=='income')
                    income=cert['annual_income_inr']/12
                    family=e['kutumba']['families'][0]
                    checks=[{'rule':'Income certificate matches family record','actual':income,'expected':family['monthly_income_inr'],'passed':income==family['monthly_income_inr']}, {'rule':'Monthly income ceiling','actual':income,'expected':scheme['monthly_income_ceiling_inr'],'passed':income<=scheme['monthly_income_ceiling_inr']}]
                    if scheme['audience']=='household':checks.append({'rule':'Active priority ration card','actual':e['ahara']['ration_cards'][0]['category'],'expected':'PHH or AAY','passed':e['ahara']['ration_cards'][0]['category'] in ['PHH','AAY']})
                    if scheme['audience']=='farmer':
                        farmers=e['fruits']['farmers'];parcels=e['bhoomi']['parcels'];crops=e['fruits']['crops']
                        checks.append({'rule':'Active farmer and clear linked land ownership','actual':len(farmers),'expected':'active farmer with matching parcel and owner','passed':bool(farmers and farmers[0]['registration_status']=='active' and parcels and crops and all(p['mutation_status']=='clear' and p['owner_person_id']==farmers[0]['person_id'] for p in parcels) and all(x['parcel_id'] in {p['parcel_id'] for p in parcels} for x in crops))})
                    if scheme['audience']=='student':checks.append({'rule':'Active student without existing scholarship','actual':len(e['education']['students']),'expected':'at least one active student with no award','passed':any(x['enrolment_status']=='active' and x['scholarship_status']=='none' for x in e['education']['students'])})
                    eligible=all(x['passed'] for x in checks);state='eligible' if eligible else 'not_eligible'
                    if not checks[0]['passed']:state='needs_correction'
                    c.execute('INSERT INTO eligibility VALUES(?,?,?,?,?)',(rid,scheme['rule_version'],int(eligible),dump(checks),now()))
                    response={'rule_version':scheme['rule_version'],'checks':checks,'demonstration_rules':True};source='Evidence store and scheme register';target='Eligibility engine'
                elif stage==5:
                    existing=c.execute('SELECT * FROM schemes.sanctions WHERE household_ref=? AND scheme_id=? AND cycle=?',(run['household_ref'],run['scheme_id'],run['cycle'])).fetchone()
                    if existing:state='duplicate_benefit';response={'existing_sanction':existing['sanction_id']}
                    else:
                        sanction='SIM-SANCTION-'+rid;c.execute('INSERT INTO schemes.sanctions VALUES(?,?,?,?,?,?,?)',(sanction,rid,run['household_ref'],run['scheme_id'],run['cycle'],amount,'sanctioned'));state='enrolled';response={'sanction_id':sanction,'amount_minor':amount,'currency':'INR','reviewer':actor}
                    target='Scheme sanction register'
                elif stage==6:
                    account=c.execute('SELECT * FROM bank.accounts WHERE household_ref=?',(run['household_ref'],)).fetchone()
                    state='account_validated' if account and account['validation_status']=='valid' and scenario!='invalid_account' else 'account_invalid'
                    response={'account_token':account['account_token'] if account else None,'validation':state,'real_account':False};source='Bank account register';target='Payment readiness'
                elif stage==7:
                    budget=c.execute('SELECT * FROM treasury.budgets WHERE scheme_id=?',(run['scheme_id'],)).fetchone()
                    available=0 if scenario=='insufficient_funds' else budget['available_minor']
                    if available<amount:state='funding_failed';response={'required_minor':amount,'available_minor':available}
                    else:
                        c.execute('UPDATE treasury.budgets SET available_minor=available_minor-? WHERE scheme_id=?',(amount,run['scheme_id']))
                        c.execute('INSERT INTO treasury.reservations VALUES(?,?,?,?,?)',('SIM-RESERVE-'+rid,rid,run['scheme_id'],amount,'reserved'));state='funded';response={'reserved_minor':amount,'currency':'INR'}
                    source='Treasury budget';target='Funding reservation'
                elif stage==8:
                    account=c.execute('SELECT account_token FROM bank.accounts WHERE household_ref=?',(run['household_ref'],)).fetchone()[0]
                    c.execute('INSERT INTO bank.instructions VALUES(?,?,?,?,?,?)',('SIM-PAY-'+rid,rid,account,'SIM-SANCTION-'+rid,amount,'accepted'));state='payment_submitted';response={'instruction_id':'SIM-PAY-'+rid,'amount_minor':amount,'idempotency_key':rid};source='Approved sanction and treasury';target='Bank instruction register'
                elif stage==9:
                    if scenario=='delayed_settlement':state='awaiting_settlement';response={'result':'callback delayed; use Retry to simulate arrival'}
                    else:state,response=self._settle(c,run,amount)
                    source='Bank callback';target='Callback inbox'
                elif stage==10:
                    settlement=c.execute('SELECT * FROM bank.settlements WHERE instruction_id=?',('SIM-PAY-'+rid,)).fetchone()
                    if not settlement:raise ModelError('No settlement evidence is available.')
                    if settlement['status']=='failed':state='payment_failed'
                    elif settlement['amount_minor']!=amount:state='reconciliation_exception'
                    elif scenario=='reversal':
                        state='reversed';c.execute("UPDATE bank.instructions SET status='reversed' WHERE run_id=?",(rid,));c.execute("UPDATE bank.settlements SET status='reversed' WHERE instruction_id=?",('SIM-PAY-'+rid,))
                    else:state='reconciled'
                    # Failed or reversed transfers release reserved funding once; settled
                    # and mismatched transfers consume it pending reconciliation.
                    if state in {'payment_failed','reversed'}:
                        changed=c.execute("UPDATE treasury.reservations SET status='released' WHERE run_id=? AND status='reserved'",(rid,)).rowcount
                        if changed:c.execute('UPDATE treasury.budgets SET available_minor=available_minor+? WHERE scheme_id=?',(amount,run['scheme_id']))
                    else:c.execute("UPDATE treasury.reservations SET status='spent' WHERE run_id=? AND status='reserved'",(rid,))
                    response={'instruction_minor':amount,'settlement_minor':settlement['amount_minor'],'result':state};source='Bank settlement and instruction';target='Reconciliation ledger'
                elif stage==11:
                    state='completed';c.execute('INSERT INTO notifications.deliveries VALUES(?,?,?,?,?,?)',('SIM-MESSAGE-'+rid,rid,run['household_ref'],'payment_reconciled','simulated_delivered',now()))
                    response={'delivery':'simulated_delivered','real_message_sent':False};source='Reconciliation ledger';target='Notification register'
                else:raise ModelError('Run is already complete.')
            if state in {'needs_correction','not_eligible','duplicate_benefit','account_invalid','funding_failed','payment_failed','reconciliation_exception','reversed','returned','source_unavailable'}:
                error=error or state.replace('_',' ').capitalize();self._case(c,run,error)
            if run['state']=='source_unavailable' and state=='evidence_ready':c.execute("UPDATE notifications.grievances SET status='resolved' WHERE run_id=?",(rid,))
            c.execute('UPDATE runs SET state=?,stage=?,version=version+1,updated_at=?,exception=? WHERE id=?',(state,stage,now(),error,rid))
            self.log(c,run,STAGES[stage],source,target,state,{'action':action,'version':version,'scenario':scenario},response,actor)
        return self.get(rid)

    def _settle(self,c,run,amount):
        rid=run['id'];status='failed' if run['scenario']=='payment_failed' else 'settled'
        settled=0 if status=='failed' else amount-100 if run['scenario']=='reconciliation_mismatch' else amount
        payload={'instruction_id':'SIM-PAY-'+rid,'status':status,'amount_minor':settled,'currency':'INR'}
        c.execute('INSERT INTO callback_inbox VALUES(?,?,?,?)',('SIM-CALLBACK-'+rid,rid,dump(payload),now()))
        c.execute('INSERT INTO bank.settlements VALUES(?,?,?,?,?)',('SIM-SETTLE-'+rid,'SIM-PAY-'+rid,settled,status,now()))
        c.execute('UPDATE bank.instructions SET status=? WHERE run_id=?',(status,rid))
        return 'callback_received',payload

    def replay_callback(self,rid,actor):
        with self.lock,self.connect() as c:
            c.execute('BEGIN IMMEDIATE');run=c.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
            if not run:raise ModelError('Training run not found.',404)
            callback=c.execute('SELECT * FROM callback_inbox WHERE run_id=?',(rid,)).fetchone()
            if not callback:raise ModelError('Receive a callback before replaying it.')
            self.log(c,run,'Callback replay','Bank callback','Callback inbox','duplicate_ignored',{'event_id':callback['event_id']},{'processed':False,'reason':'event_id already processed; no second transfer or balance change'},actor)
        return self.get(rid)

    def change_income(self,hh,income,actor):
        if not isinstance(income,int) or not 0<=income<=100000000:raise ModelError('Enter a whole monthly income from 0 to 100000000.',400)
        # Demonstrate an upstream correction in two source registers atomically.
        with self.lock,self.connect() as c:
            c.execute('ATTACH DATABASE ? AS kutumba',(str(self.root/'kutumba.sqlite'),))
            c.execute('ATTACH DATABASE ? AS revenue',(str(self.root/'revenue.sqlite'),))
            c.execute('BEGIN IMMEDIATE')
            family=c.execute('SELECT * FROM kutumba.families WHERE household_ref=?',(hh,)).fetchone()
            if not family:raise ModelError('Household not found.',404)
            before={'monthly_income_inr':family['monthly_income_inr']}
            c.execute('UPDATE kutumba.families SET monthly_income_inr=?,source_updated_at=? WHERE household_ref=?',(income,now(),hh))
            c.execute("UPDATE revenue.certificates SET annual_income_inr=?,source_updated_at=? WHERE household_ref=? AND certificate_type='income'",(income*12,now(),hh))
            c.execute('INSERT INTO source_changes(source,household_ref,before_json,after_json,actor,at) VALUES(?,?,?,?,?,?)',('kutumba+revenue',hh,dump(before),dump({'monthly_income_inr':income}),actor,now()))
        return {'updated':True,'household_ref':hh,'monthly_income_inr':income,'scope':'local source databases only; new runs fetch new evidence; existing evidence remains frozen'}

    def bundle(self):
        """Consistent SQLite backups; excludes platform auth and native databases."""
        output=io.BytesIO()
        with self.lock,tempfile.TemporaryDirectory(prefix='kdbt-register-export-') as tmp,zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
            catalogue=self.catalogue()
            z.writestr('schema-catalogue.json',dump({'version':VERSION,'sources':catalogue,'xml_mappings':XML_MAPPINGS,'public_standards':PUBLIC_STANDARDS}))
            for entry in catalogue:
                source=entry['id'];z.writestr('sql/'+source+'.sql',DDL[source])
                with self.source_db(source) as original:
                    # Serialize a transactionally coherent snapshot without exposing credentials.
                    target_path=Path(tmp)/(source+'.sqlite');target=sqlite3.connect(target_path)
                    try:original.backup(target)
                    finally:target.close()
                    z.writestr('databases/'+source+'.sqlite',target_path.read_bytes())
            with self.connect() as original:
                target_path=Path(tmp)/'orchestration.sqlite';target=sqlite3.connect(target_path)
                try:original.backup(target)
                finally:target.close()
                z.writestr('databases/orchestration.sqlite',target_path.read_bytes())
            z.writestr('sql/orchestration.sql',ORCHESTRATOR_DDL)
            z.writestr('README.txt','KarnatakaDBT synthetic external register model '+VERSION+'\nAll SQL tables and local JSON contracts are simulations, not production agency schemas.\nSee schema-catalogue.json for official references and uncertainty classifications.\nAmounts use integer paise unless a column explicitly says INR. Codes beginning SIM are fictional.\nNo real identities, financial accounts, messages or transfers.\n')
        return output.getvalue()
