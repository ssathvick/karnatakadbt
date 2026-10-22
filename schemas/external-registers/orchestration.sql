-- KarnatakaDBT simulation schema 1.0.0; not a government production DDL

CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS crosswalk(household_ref TEXT PRIMARY KEY, family_id TEXT UNIQUE NOT NULL, snapshot TEXT NOT NULL, source_version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, household_ref TEXT NOT NULL REFERENCES crosswalk(household_ref), scheme_id TEXT NOT NULL, scenario TEXT NOT NULL, cycle TEXT NOT NULL, state TEXT NOT NULL, stage INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1, snapshot TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, exception TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), stage TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL, status TEXT NOT NULL, request_json TEXT NOT NULL, response_json TEXT NOT NULL, source_table TEXT, fetched_at TEXT NOT NULL, actor TEXT NOT NULL, contract_version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence(run_id TEXT NOT NULL REFERENCES runs(id), source TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY(run_id,source));
CREATE TABLE IF NOT EXISTS mirror_households(run_id TEXT PRIMARY KEY REFERENCES runs(id), household_ref TEXT NOT NULL, data TEXT NOT NULL, synced_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS eligibility(run_id TEXT PRIMARY KEY REFERENCES runs(id), rule_version TEXT NOT NULL, eligible INTEGER NOT NULL CHECK(eligible IN (0,1)), checks TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS callback_inbox(event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), payload TEXT NOT NULL, processed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_changes(id INTEGER PRIMARY KEY, source TEXT NOT NULL, household_ref TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_run ON events(run_id,id);
CREATE INDEX IF NOT EXISTS runs_household ON runs(household_ref,created_at);
