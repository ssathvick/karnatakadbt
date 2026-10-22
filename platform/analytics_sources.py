"""Scheduled read only backend summaries and a separate aggregate reporting database."""
import json
from pathlib import Path
import psycopg2

# Fixed aggregate SQL. No demographic fields, beneficiary identifiers or bank details.
SOURCES = {'Core registry': ('karnatakadbt_core', {'registry_records': "SELECT kind,COUNT(*) FROM registry_entities WHERE kind='household' OR COALESCE((attributes->>'active')::boolean,false) GROUP BY kind", 'registry_events': "SELECT action,COUNT(*) FROM domain_events WHERE action='registry_synchronized' GROUP BY action"}), 'Core programmes': ('karnatakadbt_core', {'programme_status': 'SELECT status,COUNT(*) FROM programmes GROUP BY status', 'application_status': 'SELECT status,COUNT(*) FROM programme_applications GROUP BY status', 'historical_batches': "SELECT COALESCE(workflow_status,'Unknown'),COUNT(*) FROM beneficiary_batches WHERE id LIKE 'migrated-%' GROUP BY 1"}), 'Core approvals': ('karnatakadbt_core', {'application_decisions': "SELECT action,COUNT(*) FROM domain_events WHERE action IN ('application_check','application_enroll','application_reject') GROUP BY action", 'batch_workflow': "SELECT COALESCE(workflow_status,'Unknown'),COUNT(*) FROM beneficiary_batches WHERE id LIKE 'core-app-%' GROUP BY 1"}), 'Modern registry': ('register', {'registry_records': "SELECT 'Individual records',COUNT(*) FROM g2p_register_individuals UNION ALL SELECT 'Household records',COUNT(*) FROM g2p_register_households", 'change_request_status': "SELECT COALESCE(approval_status,'Unknown'),COUNT(*) FROM g2p_register_change_requests GROUP BY 1"}), 'PBMS': ('karnatakadbt_core', {'programme_status': 'SELECT status,COUNT(*) FROM programmes GROUP BY 1', 'current_application_status': 'SELECT status,COUNT(*) FROM programme_applications GROUP BY 1', 'historical_batch_workflow': "SELECT COALESCE(workflow_status,'Unknown'),COUNT(*) FROM beneficiary_batches WHERE id LIKE 'migrated-%' GROUP BY 1", 'core_eligibility_process': "SELECT COALESCE(eligibility_status,'Unknown'),COUNT(*) FROM beneficiary_batches WHERE id LIKE 'core-app-%' GROUP BY 1"}), 'Approval workflows': ('awe', {'request_status': "SELECT COALESCE(status,'Unknown'),COUNT(*) FROM approval_request GROUP BY 1", 'completed_turnaround_hours': "SELECT 'Median completed request hours',percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM (completed_at-created_at))/3600) FROM approval_request WHERE completed_at>=created_at UNION ALL SELECT '90th percentile completed request hours',percentile_cont(0.9) WITHIN GROUP (ORDER BY extract(epoch FROM (completed_at-created_at))/3600) FROM approval_request WHERE completed_at>=created_at"}), 'Bridge': ('bridge_db', {'instructions': "SELECT 'Disbursement instruction records',COUNT(*) FROM disbursements UNION ALL SELECT 'Reconciliation records not validated as settlement',COUNT(*) FROM disbursement_recons", 'bank_dispatch_status': "SELECT COALESCE(sponsor_bank_dispatch_status,'Unknown'),COUNT(*) FROM disbursement_batch_control GROUP BY 1"})}

def payment_metrics(r):
    # Counts are from the application's synthetic payment ledger, not a bank.
    model=r.external_register_model
    with model.connect(attached=True) as c:
        c.execute('BEGIN')
        return {
          'instruction_status': [{'label':str(x[0]),'value':float(x[1])} for x in c.execute('SELECT status,COUNT(*) FROM bank.instructions GROUP BY status')],
          'settlement_status': [{'label':str(x[0]),'value':float(x[1])} for x in c.execute('SELECT status,COUNT(*) FROM bank.settlements GROUP BY status')],
          'journey_status': [{'label':str(x[0]),'value':float(x[1])} for x in c.execute('SELECT state,COUNT(*) FROM runs GROUP BY state')]
        }


def refresh(r):
    r.execute("INSERT OR REPLACE INTO analytics_metadata VALUES('native_collector_attempt',?)",(r.stamp(),))
    config=json.loads((r.ROOT/'analytics-connections.json').read_text())
    results={}
    for source in [*SOURCES,'Custom simulated payments']:
        now=r.stamp()
        try:
            if source=='Custom simulated payments':payload=payment_metrics(r)
            else:
                database,queries=SOURCES[source]
                with psycopg2.connect(**config['sources'][database], connect_timeout=8) as conn:
                    conn.set_session(readonly=True)
                    with conn.cursor() as cur:
                        cur.execute("SET LOCAL statement_timeout='10s'")
                        payload={}
                        for name,query in queries.items():
                            cur.execute(query)
                            payload[name]=[{'label':label,'value':float(value) if value is not None else None} for label,value in cur.fetchall()]
            with r.db() as c:
                c.execute("""INSERT INTO analytics_source_cache VALUES(?,?,?,?,NULL)
                    ON CONFLICT(source) DO UPDATE SET refreshed_at=excluded.refreshed_at,payload=excluded.payload,last_attempt=excluded.last_attempt,error=NULL""",
                          (source,now,json.dumps(payload),now))
            results[source]='ok'
        except Exception:
            with r.db() as c:
                c.execute("""INSERT INTO analytics_source_cache VALUES(?,?,?,?,'refresh_failed')
                    ON CONFLICT(source) DO UPDATE SET last_attempt=excluded.last_attempt,error='refresh_failed' """, (source,'','{}',now))
            results[source]='failed'
    ops=r.analytics_snapshot()
    # This reporting database holds aggregates only, and is independent of transactional tables.
    with psycopg2.connect(**config['reporting'],connect_timeout=8) as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout='20s'")
        cur.execute('DELETE FROM aggregate_metrics')
        for source in r.rows('SELECT * FROM analytics_source_cache'):
            for metric,rows in json.loads(source['payload']).items():
                for row in rows:
                    cur.execute('INSERT INTO aggregate_metrics VALUES(%s,%s,%s,%s,%s,%s)',
                                (source['source'],metric,row['label'],row['value'],source['refreshed_at'] or None,bool(source['error'])))
        for key,value in ops.items():
            if isinstance(value,(int,float)):
                cur.execute('INSERT INTO aggregate_metrics VALUES(%s,%s,%s,%s,%s,false)',('Intake',key,key,value,r.stamp()))
        cur.execute('DELETE FROM knowledge_daily_usage')
        for row in r.rows('SELECT * FROM analytics_daily_usage'):
            cur.execute('INSERT INTO knowledge_daily_usage VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',tuple(row.values()))
        cur.execute('DELETE FROM knowledge_governance')
        # Export only aggregate editorial state and public availability, not drafts or actors.
        for row in r.rows("SELECT module,status,COUNT(*) AS articles,SUM(CASE WHEN published IS NOT NULL AND status!='archived' THEN 1 ELSE 0 END) AS live FROM km_articles GROUP BY module,status"):
            cur.execute('INSERT INTO knowledge_governance VALUES(%s,%s,%s,%s,%s)',(row['module'],row['status'],row['articles'],row['live'],r.stamp()))
    r.analytics_maintenance()
    today=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).date()
    extended=r.analytics_extended_report({'start':str(today-__import__('datetime').timedelta(days=29)),'end':str(today),'module':'','state':''})
    with psycopg2.connect(**config['reporting'],connect_timeout=8) as conn,conn.cursor() as cur:
        cur.execute('DELETE FROM extended_metrics')
        for section,metric,value,scope in r.analytics_export_rows(extended):
            cur.execute('INSERT INTO extended_metrics VALUES(%s,%s,%s,%s,%s,%s)',(section,metric,metric,value,r.stamp(),scope+'; all districts; last 30 UTC creation or event days'))
    r.execute("INSERT OR REPLACE INTO analytics_metadata VALUES('native_collector_success',?)",(r.stamp(),))
    r.execute("INSERT OR REPLACE INTO analytics_metadata VALUES('native_collector_error',?)",('' if all(v=='ok' for v in results.values()) else 'source_refresh_failed',))
    return results

if __name__=='__main__':
    import registration_app as r
    results=refresh(r)
    print(json.dumps(results))
    if any(v!='ok' for v in results.values()):raise SystemExit(1)
