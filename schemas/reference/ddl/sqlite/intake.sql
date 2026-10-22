-- Structural definitions only. sqlite_sequence is recreated automatically by AUTOINCREMENT.

CREATE TABLE ai_usage(actor TEXT,at INTEGER);

CREATE TABLE analytics_daily_usage (
          day TEXT NOT NULL, module TEXT NOT NULL, article INTEGER NOT NULL,
          version INTEGER NOT NULL, event_name TEXT NOT NULL, helpful INTEGER NOT NULL,
          events INTEGER NOT NULL, zero_results INTEGER NOT NULL,
          PRIMARY KEY(day,module,article,version,event_name,helpful));

CREATE TABLE analytics_events (
          event_id TEXT PRIMARY KEY, event_name TEXT NOT NULL, article INTEGER,
          version INTEGER, module TEXT NOT NULL, session_key TEXT NOT NULL,
          result_count INTEGER, helpful INTEGER, at TEXT NOT NULL);

CREATE TABLE analytics_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);

CREATE TABLE analytics_snapshots (
          day TEXT PRIMARY KEY, captured_at TEXT NOT NULL, payload TEXT NOT NULL);

CREATE TABLE analytics_source_cache (
          source TEXT PRIMARY KEY, refreshed_at TEXT NOT NULL, payload TEXT NOT NULL,
          last_attempt TEXT NOT NULL, error TEXT);

CREATE TABLE applications(id INTEGER PRIMARY KEY AUTOINCREMENT,sub TEXT,program INTEGER,status TEXT DEFAULT 'pending_review',portal_info INTEGER,portal_membership INTEGER,pbms_list INTEGER,error TEXT,created TEXT,UNIQUE(sub,program));

CREATE TABLE audit(id INTEGER PRIMARY KEY,actor TEXT,action TEXT,reference TEXT,at TEXT);

CREATE TABLE km_articles(id INTEGER PRIMARY KEY,slug TEXT UNIQUE NOT NULL,module TEXT NOT NULL,stage TEXT NOT NULL,audience TEXT NOT NULL,draft TEXT NOT NULL,version INTEGER NOT NULL,status TEXT NOT NULL,author TEXT NOT NULL,reviewer TEXT,published TEXT,published_version INTEGER,updated TEXT NOT NULL, review_note TEXT DEFAULT '');

CREATE TABLE km_history(id INTEGER PRIMARY KEY,article INTEGER NOT NULL,version INTEGER NOT NULL,action TEXT NOT NULL,actor TEXT NOT NULL,at TEXT NOT NULL,content TEXT NOT NULL, note TEXT DEFAULT '');

CREATE TABLE profiles(sub TEXT PRIMARY KEY,ref TEXT UNIQUE,household_ref TEXT UNIQUE,data TEXT,status TEXT DEFAULT 'pending_review',sync_status TEXT DEFAULT 'not_started',error TEXT,portal_partner INTEGER,mapping TEXT,updated TEXT, last_editor TEXT);

CREATE TABLE programs(id INTEGER PRIMARY KEY,mnemonic TEXT UNIQUE,name TEXT,amount REAL,max_income REAL,min_members INTEGER,portal_id INTEGER,cycle_id INTEGER,benefit_id INTEGER,status TEXT DEFAULT 'ACTIVE');

CREATE TABLE sessions(id TEXT PRIMARY KEY,data TEXT,expires INTEGER);

CREATE INDEX analytics_events_time ON analytics_events(at);

CREATE INDEX analytics_events_session ON analytics_events(session_key,at);
