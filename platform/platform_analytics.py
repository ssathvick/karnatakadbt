"""Aggregate sandbox analytics. No beneficiary payloads or search text are exported."""
import csv
import datetime as dt
import hashlib
import io
import json
import math
import uuid
from collections import Counter
from flask import Blueprint, abort, g, request, redirect

ROLES = {'kdbt-registration-officer', 'kdbt-verification-officer', 'kdbt-programme-supervisor', 'kdbt-intake-reviewer'}


def install(r):
    bp = Blueprint('analytics', __name__)
    with r.db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS analytics_events (
          event_id TEXT PRIMARY KEY, event_name TEXT NOT NULL, article INTEGER,
          version INTEGER, module TEXT NOT NULL, session_key TEXT NOT NULL,
          result_count INTEGER, helpful INTEGER, at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS analytics_events_time ON analytics_events(at);
        CREATE INDEX IF NOT EXISTS analytics_events_session ON analytics_events(session_key,at);
        CREATE TABLE IF NOT EXISTS analytics_daily_usage (
          day TEXT NOT NULL, module TEXT NOT NULL, article INTEGER NOT NULL,
          version INTEGER NOT NULL, event_name TEXT NOT NULL, helpful INTEGER NOT NULL,
          events INTEGER NOT NULL, zero_results INTEGER NOT NULL,
          PRIMARY KEY(day,module,article,version,event_name,helpful));
        CREATE TABLE IF NOT EXISTS analytics_snapshots (
          day TEXT PRIMARY KEY, captured_at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS analytics_source_cache (
          source TEXT PRIMARY KEY, refreshed_at TEXT NOT NULL, payload TEXT NOT NULL,
          last_attempt TEXT NOT NULL, error TEXT);
        CREATE TABLE IF NOT EXISTS analytics_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
        ''')
        c.execute("INSERT OR IGNORE INTO analytics_metadata VALUES('tracking_started_at',?)", (r.stamp(),))

    def require():
        r.require_user()
        roles={role.replace('iqs-','kdbt-') for role in g.user.get('roles',[])}
        if g.session.get('mode') != 'staff' or not (g.staff or ROLES & roles):
            abort(403, 'Analytics requires an assigned staff workspace role.')

    def session_key():
        return hashlib.sha256(g.sid.encode()).hexdigest()

    def record(name, module='', article=None, version=None, result_count=None, helpful=None, event_id=None):
        now = r.stamp()
        key = session_key()
        hour = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).isoformat()
        with r.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM analytics_events WHERE event_id=?', (event_id,)).fetchone():
                return False
            if c.execute('SELECT COUNT(*) FROM analytics_events WHERE session_key=? AND at>=?', (key, hour)).fetchone()[0] >= 120:
                if name == 'search_completed': return False
                abort(429, 'Usage event limit reached. Try again later.')
            if name == 'feedback_submitted' and c.execute("SELECT 1 FROM analytics_events WHERE session_key=? AND article=? AND version=? AND event_name='feedback_submitted' AND substr(at,1,10)=?", (key, article, version, now[:10])).fetchone():
                return False
            c.execute('INSERT INTO analytics_events VALUES(?,?,?,?,?,?,?,?,?)',
                      (event_id or str(uuid.uuid4()), name, article, version, module, key, result_count, helpful, now))
            c.execute('''INSERT INTO analytics_daily_usage VALUES(?,?,?,?,?,?,1,?)
              ON CONFLICT(day,module,article,version,event_name,helpful)
              DO UPDATE SET events=events+1,zero_results=zero_results+excluded.zero_results''',
                      (now[:10], module, article or 0, version or 0, name, -1 if helpful is None else helpful, int(name == 'search_completed' and result_count == 0)))
        return True

    # Called only after the knowledge library has applied all search and audience filters.
    r.analytics_search = lambda module, count: record('search_completed', module=module, result_count=count)

    @bp.post(r.PREFIX + '/api/analytics/events')
    def event():
        # The application's existing POST guard validates session CSRF before this handler.
        try:
            event_id = str(uuid.UUID(request.form['event_id']))
            aid = int(request.form['article_id'])
            version = int(request.form['version'])
        except (KeyError, ValueError, TypeError):
            abort(400, 'Provide a valid event ID, article and published version.')
        name = request.form.get('event_name')
        if name not in {'guide_opened', 'feedback_submitted'}:
            abort(400, 'Unsupported usage event.')
        a = r.one("SELECT * FROM km_articles WHERE id=? AND published IS NOT NULL AND status!='archived'", (aid,))
        if not a or a['published_version'] != version:
            abort(409, 'Reload the published guide before recording feedback.')
        helpful = None
        if name == 'feedback_submitted':
            if request.form.get('helpful') not in {'0', '1'}:
                abort(400, 'Choose helpful or not helpful.')
            helpful = int(request.form['helpful'])
        accepted = record(name, module=json.loads(a['published'])['module'], article=aid,
                          version=version, helpful=helpful, event_id=event_id)
        return {'accepted': accepted}

    def counts(items, key):
        return [{'label': k, 'count': v} for k, v in sorted(Counter(x[key] for x in items).items())]

    def operations(state='', programme=''):
        profiles = r.rows('SELECT sub,data,status,sync_status,error FROM profiles')
        for p in profiles:
            try:
                d = json.loads(p.pop('data'))
                p['state'] = d.get('state_name') or 'Unknown'
                p['members'] = len(d.get('members', []))
            except (ValueError, TypeError):
                p.update(state='Unknown', members=0)
        all_states = sorted({p['state'] for p in profiles})
        programmes = r.rows('SELECT id,name FROM programs ORDER BY name')
        apps = r.rows('SELECT id,sub,program,status,created,error FROM applications')
        if programme:
            apps = [a for a in apps if str(a['program']) == programme]
            subjects = {a['sub'] for a in apps}
            profiles = [p for p in profiles if p['sub'] in subjects]
        if state:
            profiles = [p for p in profiles if p['state'] == state]
        subjects = {p['sub'] for p in profiles}
        apps = [a for a in apps if a['sub'] in subjects]
        return {'profiles': len(profiles), 'members': sum(p['members'] for p in profiles),
                'applications': len(apps), 'review_backlog': sum(p['status'] == 'pending_review' for p in profiles),
                'sync_pending': sum(p['status'] == 'approved' and p['sync_status'] != 'complete' for p in profiles),
                'exceptions': sum(bool(p['error']) for p in profiles) + sum(bool(a['error']) for a in apps),
                'profile_status': counts(profiles, 'status'), 'application_status': counts(apps, 'status'),
                'geography': counts(profiles, 'state'), 'states': all_states, 'programmes': programmes}

    def knowledge(module, start, end):
        articles = r.rows('SELECT id,module,status,published,published_version FROM km_articles')
        if module:
            articles = [a for a in articles if a['module'] == module]
        ids = {a['id'] for a in articles}
        usage = r.rows('SELECT * FROM analytics_daily_usage WHERE day>=? AND day<=?' + (' AND module=?' if module else ''),
                       (start, end, module) if module else (start, end))
        totals = Counter()
        article_counts = Counter()
        versions = {}
        for u in usage:
            totals[u['event_name']] += u['events']
            totals['zero_results'] += u['zero_results']
            if u['event_name'] == 'feedback_submitted':
                totals['helpful'] += u['events'] if u['helpful'] == 1 else 0
            if u['event_name'] == 'guide_opened':
                article_counts[u['article']] += u['events']
            if u['article']:
                entry = versions.setdefault((u['article'], u['version']), {'article': u['article'], 'version': u['version'], 'opens': 0, 'votes': 0, 'helpful': 0})
                if u['event_name'] == 'guide_opened': entry['opens'] += u['events']
                if u['event_name'] == 'feedback_submitted':
                    entry['votes'] += u['events']; entry['helpful'] += u['events'] if u['helpful'] == 1 else 0
        # Pair each submission with its first review decision for that version.
        pending = {}; hours = []; actions = Counter()
        for e in r.rows('SELECT article,version,action,at FROM km_history ORDER BY id'):
            if e['article'] not in ids: continue
            key = (e['article'], e['version'])
            if e['action'] == 'submit': pending[key] = e['at']
            if e['action'] in {'review', 'return'}:
                if start <= e['at'][:10] <= end:
                    actions[e['action']] += 1
                    if key in pending:
                        try:
                            duration = (dt.datetime.fromisoformat(e['at']) - dt.datetime.fromisoformat(pending[key])).total_seconds()/3600
                            if math.isfinite(duration) and duration >= 0: hours.append(duration)
                        except (ValueError, TypeError): pass
                pending.pop(key, None)
        hours.sort()
        def percentile(p):
            if not hours: return None
            pos=(len(hours)-1)*p; lo=int(pos); hi=min(lo+1,len(hours)-1)
            return round(hours[lo]+(hours[hi]-hours[lo])*(pos-lo),2)
        live = [a for a in articles if a['published'] is not None and a['status'] != 'archived']
        titles = {a['id']: json.loads(a['published'])['title'] for a in live}
        return {'live': len(live), 'review_backlog': sum(a['status']=='in_review' for a in articles),
                'awaiting_publication': sum(a['status']=='reviewed' for a in articles),
                'editorial_status': counts(articles, 'status'), 'usage': dict(totals),
                'zero_result_rate': round(100*totals['zero_results']/totals['search_completed'],1) if totals['search_completed'] else None,
                'helpfulness': round(100*totals['helpful']/totals['feedback_submitted'],1) if totals['feedback_submitted'] else None,
                'review_median_hours': percentile(.5), 'review_p90_hours': percentile(.9), 'review_episodes': len(hours),
                'returns': actions['return'], 'decisions': actions['return']+actions['review'],
                'popular': [{'article': a, 'title': titles.get(a, 'Archived or superseded guidance'), 'opens': n} for a,n in article_counts.most_common(10)],
                'versions': sorted(versions.values(),key=lambda x:(x['article'],x['version']))}

    def filters():
        today=dt.datetime.now(dt.timezone.utc).date()
        try:
            start=dt.date.fromisoformat(request.args.get('start',str(today-dt.timedelta(days=29))))
            end=dt.date.fromisoformat(request.args.get('end',str(today)))
            if start>end or (end-start).days>366 or end>today: raise ValueError()
        except ValueError: abort(400,'Choose a valid date range of up to 367 days ending today or earlier.')
        module=request.args.get('module','');state=request.args.get('state','');programme=request.args.get('programme','')
        if module and module not in __import__('knowledge_management').MODULES: abort(400,'Unknown knowledge module.')
        if programme and not r.one('SELECT id FROM programs WHERE id=?',(programme,)): abort(400,'Unknown programme.')
        if state and state not in operations()['states']: abort(400,'Unknown state.')
        return module,state,programme,str(start),str(end)

    def report():
        module,state,programme,start,end=filters()
        sources=[]
        for row in r.rows('SELECT * FROM analytics_source_cache ORDER BY source'):
            try:
                stale=(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(row['refreshed_at'])).total_seconds()>1800
            except (ValueError,TypeError):stale=True
            sources.append({'source':row['source'],'refreshed_at':row['refreshed_at'],'last_attempt':row['last_attempt'],
                            'error': bool(row['error']), 'stale':stale, 'data':json.loads(row['payload'])})
        result={'generated_at':r.stamp(),'timezone':'UTC','scope':'Existing synthetic sandbox staff scope across all intake records',
                'filters':{'module':module,'state':state,'programme':programme,'start':start,'end':end},
                'operations':operations(state,programme),'knowledge':knowledge(module,start,end),'sources':sources,
                'tracking_started_at':r.one("SELECT value FROM analytics_metadata WHERE key='tracking_started_at'")['value'],
                'snapshots':[{'day':x['day'],'captured_at':x['captured_at'],'profiles':json.loads(x['payload'])['profiles'],
                              'review_backlog':json.loads(x['payload'])['review_backlog']} for x in r.rows('SELECT * FROM analytics_snapshots WHERE day>=? AND day<=? ORDER BY day',(start,end))]}
        if hasattr(r,'analytics_extended_report'):result['extended']=r.analytics_extended_report(result['filters'])
        return result

    @bp.get(r.PREFIX+'/analytics')
    def dashboard():
        if not g.user: return redirect(r.PREFIX+'/login?mode=staff&analytics=1')
        require()
        return r.page('analytics.html',report=report(),modules=__import__('knowledge_management').MODULES)

    @bp.get(r.PREFIX+'/api/analytics')
    def api():
        require();return report()

    @bp.get(r.PREFIX+'/api/analytics/export.csv')
    def export():
        require()
        if not (g.staff or {'kdbt-programme-supervisor','kdbt-intake-reviewer'} & {role.replace('iqs-','kdbt-') for role in g.user.get('roles',[])}): abort(403,'Aggregate exports require supervisor access.')
        data=report();buf=io.StringIO();writer=csv.writer(buf)
        writer.writerow(['section','measure','count','generated_at','scope'])
        for section in ['operations','knowledge']:
            for key,value in data[section].items():
                if isinstance(value,(int,float)):
                    writer.writerow([section,key,value,data['generated_at'],data['scope']])
        response=r.app.make_response(buf.getvalue());response.mimetype='text/csv'
        response.headers['Content-Disposition']='attachment; filename="platform-analytics.csv"'
        return response

    def snapshot():
        now=r.stamp();payload=operations()
        with r.db() as c:
            c.execute('INSERT INTO analytics_snapshots VALUES(?,?,?) ON CONFLICT(day) DO UPDATE SET captured_at=excluded.captured_at,payload=excluded.payload',(now[:10],now,json.dumps(payload)))
            cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=90)).isoformat()
            c.execute('DELETE FROM analytics_events WHERE at<?',(cutoff,))
            c.execute('DELETE FROM analytics_daily_usage WHERE day<?',((dt.datetime.now(dt.timezone.utc).date()-dt.timedelta(days=366)).isoformat(),))
            c.execute('DELETE FROM analytics_snapshots WHERE day<?',((dt.datetime.now(dt.timezone.utc).date()-dt.timedelta(days=366)).isoformat(),))
        return payload
    r.analytics_snapshot=snapshot
    r.analytics_full_report=report
    r.app.register_blueprint(bp)
