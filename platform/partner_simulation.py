"""Synthetic partner contracts and isolated, transactional DBT demonstrations.

Uses the platform's staff authentication and CSRF guard. Never writes beneficiary,
PBMS, bank or Bridge tables. Contracts are local simulations, not agency APIs.
"""
import datetime as dt
import json
import sqlite3
import uuid
from collections import Counter
from flask import Blueprint, abort, g, request, redirect

SCENARIOS = {
    'success': 'Successful transfer and settlement',
    'identity_mismatch': 'Identity verification rejected',
    'ineligible': 'Household fails programme eligibility',
    'invalid_account': 'Bank account validation rejected',
    'insufficient_funds': 'Treasury has insufficient funds',
    'payment_failed': 'Bank rejects the transfer',
    'delayed_settlement': 'Transfer accepted; settlement delayed',
    'reconciliation_mismatch': 'Settlement amount differs from instruction',
    'reversal': 'Successful transfer subsequently reversed',
}
ROLES = {'kdbt-programme-supervisor', 'kdbt-intake-reviewer'}


def install(r):
    bp = Blueprint('partner_simulation', __name__)
    path = r.ROOT / 'partner-simulation.sqlite'

    def db():
        c = sqlite3.connect(path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA foreign_keys=ON')
        return c

    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS runs(
          id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, scenario TEXT NOT NULL,
          state TEXT NOT NULL, amount_minor INTEGER NOT NULL, currency TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, due_at TEXT,
          payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
          service TEXT NOT NULL, status TEXT NOT NULL, at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS events_run ON events(run_id,at);
        CREATE TABLE IF NOT EXISTS callbacks(
          event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
          status TEXT NOT NULL, received_at TEXT NOT NULL);
        ''')
    path.chmod(0o600)

    def require():
        r.require_user()
        if g.session.get('mode') != 'staff' or not ROLES.intersection(g.user.get('roles', [])):
            abort(403, 'Simulation requires a programme supervisor or intake reviewer role.')

    def now():
        return dt.datetime.now(dt.timezone.utc).isoformat()

    def event(c, run_id, service, status, payload):
        c.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',
                  (str(uuid.uuid4()), run_id, service, status, now(), json.dumps(payload)))

    def partner(service, scenario):
        # No arbitrary identities, account numbers, addresses or external URLs are accepted.
        if service == 'identity':
            return {'verified': scenario != 'identity_mismatch', 'identity_reference': 'SIM-Synthetic identity ID-000001', 'consent_reference': 'SIM-CONSENT-001', 'synthetic': True}
        if service == 'social-register':
            return {'household_reference': 'SIM-HH-000001', 'state': 'Mysuru', 'members': 4, 'eligible': scenario != 'ineligible', 'synthetic': True}
        if service == 'programme':
            return {'programme_reference': 'SIM-CASH-TRANSFER', 'amount_minor': 2500000, 'currency': 'INR', 'eligible': scenario != 'ineligible', 'synthetic': True}
        if service == 'treasury':
            return {'funding_reference': 'SIM-FUND-001', 'approved': scenario != 'insufficient_funds', 'amount_minor': 2500000, 'currency': 'INR', 'synthetic': True}
        if service == 'account':
            return {'account_reference': 'SIM-ACCOUNT-001', 'valid': scenario != 'invalid_account', 'account_name': 'Synthetic Beneficiary One', 'synthetic': True}
        if service == 'payment':
            return {'status': 'failed' if scenario == 'payment_failed' else 'accepted', 'reason_code': 'SIM_BANK_REJECTED' if scenario == 'payment_failed' else None, 'synthetic': True}
        if service == 'notification':
            return {'delivery_status': 'simulated_delivered', 'channel': 'simulated_sms', 'synthetic': True}
        if service == 'grievance':
            return {'case_reference': 'SIM-CASE-001', 'status': 'open', 'synthetic': True}
        if service == 'reconciliation':
            return {'settled_amount_minor': 2400000 if scenario == 'reconciliation_mismatch' else 2500000, 'currency': 'INR', 'reversed': scenario == 'reversal', 'synthetic': True}
        abort(404, 'Unknown simulated partner service.')

    def run(scenario, key):
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM runs WHERE request_key=?', (key,)).fetchone()
            if old:
                if old['scenario'] != scenario:
                    abort(409, 'This request key was already used for another scenario.')
                return old['id']
            if c.execute('SELECT COUNT(*) FROM runs').fetchone()[0] >= 1000:
                abort(409, 'Archive/reset the simulation before creating more than 1,000 runs.')
            rid = str(uuid.uuid4())
            at = now()
            payload = {'synthetic': True, 'beneficiary': 'Synthetic Beneficiary One',
                       'household_reference': 'SIM-HH-000001', 'programme_reference': 'SIM-CASH-TRANSFER'}
            c.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (rid, key, scenario, 'registered', 2500000, 'INR', at, at, None, json.dumps(payload)))
            event(c, rid, 'registration', 'registered', payload)
            stages = [('identity', 'verified', 'verified'), ('social-register', 'eligible', 'eligible'),
                      ('programme', 'eligible', 'enrolled'), ('account', 'valid', 'validated'),
                      ('treasury', 'approved', 'funded')]
            state = 'registered'
            for service, flag, success in stages:
                result = partner(service, scenario)
                state = success if result[flag] else service + '_rejected'
                event(c, rid, service, state, result)
                if not result[flag]:
                    event(c, rid, 'grievance', 'open', partner('grievance', scenario))
                    break
                if service == 'programme':
                    event(c, rid, 'approval', 'approved', {'approval_reference': 'SIM-APPROVAL-' + rid, 'synthetic': True})
            due = None
            if state == 'funded':
                result = partner('payment', scenario)
                state = 'payment_' + result['status']
                event(c, rid, 'payment', state, {**result, 'payment_id': rid, 'amount_minor': 2500000, 'currency': 'INR'})
                if state == 'payment_accepted':
                    due = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=120 if scenario == 'delayed_settlement' else 10)).isoformat()
                else:
                    event(c, rid, 'grievance', 'open', partner('grievance', scenario))
            event(c, rid, 'notification', 'simulated_delivered', partner('notification', scenario))
            c.execute('UPDATE runs SET state=?,due_at=?,updated_at=? WHERE id=?', (state, due, now(), rid))
            return rid

    def callback(c, rid, event_id, status):
        item = c.execute('SELECT * FROM runs WHERE id=?', (rid,)).fetchone()
        if not item:
            abort(404, 'Simulation run not found.')
        existing = c.execute('SELECT * FROM callbacks WHERE event_id=?', (event_id,)).fetchone()
        if existing:
            if existing['run_id'] != rid or existing['status'] != status:
                abort(409, 'Callback ID reused with different contents.')
            return False
        if item['state'] != 'payment_accepted':
            abort(409, 'Only accepted payments can receive a completion callback.')
        expected = 'reversed' if item['scenario'] == 'reversal' else 'successful'
        if status != expected:
            abort(409, 'Callback status does not match this synthetic scenario.')
        c.execute('INSERT INTO callbacks VALUES(?,?,?,?)', (event_id, rid, status, now()))
        if status == 'reversed':
            event(c, rid, 'bank-callback', 'successful', {'payment_id': rid, 'status': 'successful', 'synthetic': True})
        event(c, rid, 'bank-callback', status, {'event_id': event_id, 'payment_id': rid, 'status': status, 'synthetic': True})
        settlement = partner('reconciliation', item['scenario'])
        state = 'reversed' if settlement['reversed'] else 'reconciliation_mismatch' if settlement['settled_amount_minor'] != item['amount_minor'] else 'settled'
        event(c, rid, 'reconciliation', state, settlement)
        if state != 'settled':
            event(c, rid, 'grievance', 'open', partner('grievance', item['scenario']))
        event(c, rid, 'notification', 'simulated_delivered', partner('notification', item['scenario']))
        c.execute('UPDATE runs SET state=?,due_at=NULL,updated_at=? WHERE id=?', (state, now(), rid))
        return True

    def tick():
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            for item in c.execute("SELECT * FROM runs WHERE state='payment_accepted' AND due_at<=?", (now(),)).fetchall():
                eid = str(uuid.uuid5(uuid.NAMESPACE_URL, 'sim-callback:' + item['id']))
                callback(c, item['id'], eid, 'reversed' if item['scenario'] == 'reversal' else 'successful')

    def report():
        with db() as c:
            items = [dict(x) for x in c.execute('SELECT * FROM runs ORDER BY created_at DESC LIMIT 1000')]
            counts = dict(Counter(x['state'] for x in items))
            settled = sum(x['amount_minor'] for x in items if x['state'] == 'settled')
            return {'synthetic': True, 'scope': 'Isolated partner simulation; excluded from live KarnatakaDBT totals',
                    'runs': items, 'counts': counts, 'settled_amount_minor': settled, 'currency': 'INR'}

    @bp.get(r.PREFIX + '/simulation')
    def console():
        if not g.user:
            return redirect(r.PREFIX + '/login?mode=staff&simulation=1')
        require()
        return r.page('simulation.html', report=report(), scenarios=SCENARIOS, request_key=str(uuid.uuid4()))

    @bp.post(r.PREFIX + '/api/simulation/runs')
    def start():
        require()
        scenario = request.form.get('scenario')
        if scenario not in SCENARIOS:
            abort(400, 'Choose a supported scenario.')
        try:
            key = str(uuid.UUID(request.form.get('request_key', '')))
        except ValueError:
            abort(400, 'Provide a UUID request key.')
        rid = run(scenario, key)
        if request.form.get('console') == '1':
            return redirect(r.PREFIX + '/simulation/run/' + rid)
        return {'run_id': rid, 'synthetic': True}, 200

    @bp.get(r.PREFIX + '/simulation/run/<rid>')
    def detail(rid):
        require()
        with db() as c:
            item = c.execute('SELECT * FROM runs WHERE id=?', (rid,)).fetchone()
            if not item:
                abort(404)
            events = [dict(x) for x in c.execute('SELECT * FROM events WHERE run_id=? ORDER BY at,rowid', (rid,))]
        return r.page('simulation-run.html', run=dict(item), events=events, scenarios=SCENARIOS)

    @bp.get(r.PREFIX + '/api/simulation/report')
    def metrics():
        require()
        return report()

    @bp.post(r.PREFIX + '/api/simulation/partners/<service>')
    def service_api(service):
        require()
        scenario = request.form.get('scenario', 'success')
        if scenario not in SCENARIOS:
            abort(400, 'Unknown scenario.')
        return partner(service, scenario)

    @bp.post(r.PREFIX + '/api/simulation/callback')
    def receive():
        require()
        try:
            eid = str(uuid.UUID(request.form.get('event_id', '')))
        except ValueError:
            abort(400, 'Provide a UUID event ID.')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            accepted = callback(c, request.form.get('run_id', ''), eid, request.form.get('status', ''))
        return {'accepted': accepted, 'synthetic': True}

    @bp.post(r.PREFIX + '/api/simulation/reset')
    def reset():
        require()
        if request.form.get('confirmation') != 'RESET SYNTHETIC RUNS':
            abort(400, 'Enter RESET SYNTHETIC RUNS to clear simulation data.')
        with db() as c:
            c.execute('DELETE FROM runs')
        return redirect(r.PREFIX + '/simulation')

    @bp.get(r.PREFIX + '/api/simulation/schema')
    def schema():
        require()
        return r.app.response_class((r.BASE_DIR.parent / 'schemas' / 'simulation-openapi.json').read_text(), mimetype='application/json')

    r.simulation_tick = tick
    r.simulation_report = report
    r.simulation_db = db
    r.app.register_blueprint(bp)

