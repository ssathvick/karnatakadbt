"""Connect independent domain transactions to the existing intake projections."""
import json,os
from pathlib import Path
from flask import g,has_request_context,abort,request,redirect
from sqlalchemy import select,update
from core_store import CoreStore,entities,programmes,applications,outbox,DomainConflict

class Runtime:
    def __init__(self,r,url=None):
        self.r=r
        if url is None:url=json.loads((r.ROOT/'core-connections.json').read_text())['url']
        self.store=CoreStore(url)
        policy=r.ROOT/'g2p-migration-policy.json'
        self.legacy_registry_projection=json.loads(policy.read_text()).get('legacy_registry_projection',True) if policy.exists() else True
        self.native_registry_writer=None
        if policy.exists() and json.loads(policy.read_text()).get('registry_projection_mode')=='standalone':
            from standalone_ownership import portal_writer
            self.native_registry_writer=portal_writer(json.loads((r.ROOT/'native-registry-writer-settings.json').read_text()))
            self.legacy_registry_projection=False
        if policy.exists() and json.loads(policy.read_text()).get('registry_projection_mode')=='native':
            from sqlalchemy import create_engine
            from registry_approval_store import RegistryApprovalStore
            from registry_portal_writer import NativePortalRegistryWriter
            from registry_reverse_journal import RegistryReverseJournal
            configuration=json.loads((r.ROOT/'native-registry-writer-settings.json').read_text())
            engine=create_engine(configuration['url'],hide_parameters=True)
            from registry_native_write_capture import bind_engine
            bind_engine(engine,Path(configuration['native_capture_key_path']).read_text().strip(),writer='native-portal')
            contract=json.loads(Path(configuration['source_contract_path']).read_text())
            journal=RegistryReverseJournal(engine,contract,Path(configuration['reverse_journal_key_path']).read_bytes())
            self.native_registry_writer=NativePortalRegistryWriter(RegistryApprovalStore(engine),scope=configuration['handoff_scope'],reverse_journal=journal)
            self.legacy_registry_projection=False

    def actor(self):return g.user.get('sub','system') if has_request_context() and hasattr(g,'user') else 'system'

    def project_programme(self,pid):
        with self.store.engine.connect() as c:p=dict(c.execute(select(programmes).where(programmes.c.id==pid)).mappings().one())
        self.r.execute('INSERT INTO programs(id,mnemonic,name,amount,max_income,min_members,status) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET mnemonic=excluded.mnemonic,name=excluded.name,amount=excluded.amount,max_income=excluded.max_income,min_members=excluded.min_members,status=excluded.status',(pid,p['mnemonic'],p['name'],p['amount_minor']/100,p['income_limit_minor']/100,p['min_members'],p['status']))
        self.store.mark_projection('programme:'+str(pid))

    def create_programme(self,mnemonic,name,amount,income,minimum,rules=None):
        with self.r.LOCK:return self._create_programme(mnemonic,name,amount,income,minimum,rules)

    def _create_programme(self,mnemonic,name,amount,income,minimum,rules=None):
        pid=self.store.create_programme(mnemonic,name,amount,income,minimum,self.actor(),rules)
        self.project_programme(pid)
        return pid

    def programme_form(self):
        r=self.r;r.require_user()
        roles={x.replace('iqs-','kdbt-') for x in g.user.get('roles',[])}
        if g.session.get('mode')!='staff' or not ('kdbt-programme-supervisor' in roles or g.session.get('role')=='supervisor'):abort(403,'Programme supervisor access is required.')
        try:
            suffix=r.clean(request.form.get('mnemonic')).upper()
            if not suffix.replace('_','').isalnum() or len(suffix)>30:raise ValueError('Use a unique mnemonic of at most 30 letters, digits and underscores.')
            self.create_programme('KA_'+suffix,r.clean(request.form.get('name')),request.form.get('amount'),request.form.get('max_income'),int(request.form.get('min_members','')),request.form.get('rules') or None)
            r.audit('programme_created',suffix)
        except (ValueError,TypeError) as e:abort(400,str(e))
        return redirect(r.PREFIX+'/next/#Programmes')

    def update_programme(self,pid,version,name,amount,income,minimum,status,rules=None):
        with self.r.LOCK:
            self.store.update_programme(pid,version,name,amount,income,minimum,status,self.actor(),rules)
            self.project_programme(pid)

    def apply_form(self,pid):
        r=self.r;r.require_user()
        with r.LOCK:
            p=r.one('SELECT * FROM profiles WHERE sub=?',(g.user['sub'],));programme=r.one("SELECT * FROM programs WHERE id=? AND status='ACTIVE'",(pid,))
            if g.session.get('mode')!='beneficiary' or not p or p['status']!='approved' or p['sync_status']!='complete' or not programme:abort(409,'An approved synchronized household and active programme are required.')
            r.execute('INSERT OR IGNORE INTO applications(sub,program,created) VALUES(?,?,?)',(g.user['sub'],pid,r.stamp()))
            a=r.one('SELECT * FROM applications WHERE sub=? AND program=?',(g.user['sub'],pid))
            self.link_application(a);r.audit('programme_application',a['id'])
        return redirect(r.PREFIX+'/next/#Programmes')

    def decision_form(self,aid,action):
        r=self.r;r.require_staff()
        with r.LOCK:
            try:self.decide_application(aid,action)
            except DomainConflict as e:abort(409,str(e))
            r.audit('application_'+action,aid)
        return redirect(r.PREFIX+'/next/#Programmes')

    def project_registry(self,sub):
        r=self.r;p=r.one('SELECT * FROM profiles WHERE sub=?',(sub,))
        if not p:raise DomainConflict('Household not found.')
        household=p['household_ref']
        # The independent Core is the sole active registry. Verify the durable
        # version before acknowledging the intake projection; retries must never
        # mark a newer intake revision complete using an older Core record.
        with self.store.engine.connect() as c:
            record=c.execute(select(entities).where(
                entities.c.reference==household,entities.c.kind=='household'
            )).mappings().first()
        if not record or record['source_version']!=p['updated']:
            raise DomainConflict('The current household revision has not reached the Core registry.')
        if self.native_registry_writer is not None:
            self.native_registry_writer.project(r,p)
        elif self.legacy_registry_projection and hasattr(r,'pg'):
            from legacy_registry_projection import project
            project(r,p)
        r.execute("UPDATE profiles SET sync_status='complete',mapping=?,error=NULL WHERE sub=? AND updated=?",(json.dumps({'backend':'KarnatakaDBT Core','registry_reference':household,'version':p['updated']}),sub,p['updated']))
        self.store.mark_projection('registry:'+household)

    def sync_profile(self,sub):
        with self.r.LOCK:return self._sync_profile(sub)

    def _sync_profile(self,sub):
        p=self.r.one('SELECT * FROM profiles WHERE sub=?',(sub,))
        if not p or p['status']!='approved':raise DomainConflict('An approved registration is required.')
        self.store.registry(p['household_ref'],json.loads(p['data']),sub,p['updated'],self.actor())
        try:self.project_registry(sub)
        except Exception:
            self.store.mark_projection('registry:'+p['household_ref'],error=True)
            raise

    def sync_location(self,reference):
        p=self.r.one('SELECT * FROM profiles WHERE household_ref=?',(reference,))
        if not p:return False
        # Only approved records belong in the active registry; draft coordinates
        # remain in intake until independent review.
        if p['status']=='approved':self.sync_profile(p['sub'])
        self.r.execute("UPDATE geography_sync SET status='complete',error=NULL,updated=? WHERE reference=?",(self.r.stamp(),reference))
        return True

    def link_application(self,a):
        p=self.r.one('SELECT * FROM profiles WHERE sub=?',(a['sub'],))
        if not p or p['status']!='approved' or p['sync_status']!='complete':raise DomainConflict('Approve and synchronize the household first.')
        self.store.application(a,p['household_ref'],self.actor())
        # Compatibility columns are local identifiers, no longer remote ORM IDs.
        self.r.execute('UPDATE applications SET portal_info=?,portal_membership=?,error=NULL WHERE id=?',(a['id'],a['id'],a['id']))

    def project_application(self,aid):
        with self.store.engine.connect() as c:a=c.execute(select(applications).where(applications.c.id==aid)).mappings().one()
        self.r.execute('UPDATE applications SET status=?,pbms_list=?,error=NULL WHERE id=?',(a['status'],aid,aid))
        self.store.mark_projection('application:'+str(aid))

    def decide_application(self,aid,action):
        a=self.r.one('SELECT * FROM applications WHERE id=?',(aid,))
        if not a:raise DomainConflict('Application not found.')
        p=self.r.one('SELECT * FROM profiles WHERE sub=?',(a['sub'],))
        if not p or p['status']!='approved' or p['sync_status']!='complete':raise DomainConflict('The registration must remain approved and synchronized.')
        self.link_application(a)
        status=self.store.decide(aid,action,self.actor())
        self.project_application(aid)
        return status

    def refresh_rules(self,pid):
        # Eligibility reads versioned programme policy directly, with no compiled
        # ORM domain or generated SQL based on household identifiers.
        return pid

    def reconcile(self):
        with self.r.LOCK:return self._reconcile()

    def _reconcile(self):
        r=self.r;r.execute('DELETE FROM sessions WHERE expires<?',(__import__('time').time(),))
        for item in self.store.rows(outbox):
            if item['status']=='complete':continue
            try:
                if item['kind']=='programme':self.project_programme(item['payload']['id'])
                elif item['kind']=='application':self.project_application(item['payload']['id'])
                elif item['kind']=='registry':self.project_registry(item['payload']['subject'])
            except Exception:self.store.mark_projection(item['key'],error=True)
        for p in r.rows("SELECT * FROM profiles WHERE status='approved' AND sync_status!='complete'"):
            try:self.sync_profile(p['sub'])
            except Exception:pass
        for a in r.rows('SELECT * FROM applications WHERE portal_info IS NULL'):
            try:self.link_application(a)
            except Exception:r.execute('UPDATE applications SET error=? WHERE id=?',('Domain application projection pending; will retry.',a['id']))
        for a in r.rows("SELECT * FROM applications WHERE status='checking_eligibility'"):
            try:self.decide_application(a['id'],'check')
            except Exception:r.execute('UPDATE applications SET error=? WHERE id=?',('Eligibility processing needs attention; inspect the domain service.',a['id']))

def bind(r,url=None):
    runtime=Runtime(r,url)
    r.backend=runtime
    r.sync_profile=runtime.sync_profile;r.create_program=runtime.create_programme;r.update_rules=runtime.refresh_rules;r.link_portal_application=runtime.link_application
    r.start_eligibility=lambda a:runtime.decide_application(a['id'],'check')
    r.reconcile=runtime.reconcile
    for rule in list(r.app.url_map.iter_rules()):
        if rule.rule==r.PREFIX+'/staff/program' and 'POST' in rule.methods:r.app.view_functions[rule.endpoint]=runtime.programme_form
        elif rule.rule==r.PREFIX+'/apply/<int:pid>':r.app.view_functions[rule.endpoint]=runtime.apply_form
        elif rule.rule==r.PREFIX+'/staff/application/<int:aid>/<action>':r.app.view_functions[rule.endpoint]=runtime.decision_form
    return runtime
