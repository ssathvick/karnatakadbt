-- Structural definitions only. sqlite_sequence is recreated automatically by AUTOINCREMENT.

CREATE TABLE callbacks(
          event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
          status TEXT NOT NULL, received_at TEXT NOT NULL);

CREATE TABLE events(
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
          service TEXT NOT NULL, status TEXT NOT NULL, at TEXT NOT NULL, payload TEXT NOT NULL);

CREATE TABLE runs(
          id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, scenario TEXT NOT NULL,
          state TEXT NOT NULL, amount_minor INTEGER NOT NULL, currency TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, due_at TEXT,
          payload TEXT NOT NULL);

CREATE INDEX events_run ON events(run_id,at);
