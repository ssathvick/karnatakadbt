CREATE TABLE IF NOT EXISTS certify.native_presentation_recovery (
    id text PRIMARY KEY CHECK (length(id) = 64),
    kind text NOT NULL CHECK (kind IN ('VP_RECOVERY', 'VP_RECOVERY_INDEX')),
    content bytea NOT NULL CHECK (octet_length(content) <= 1048576),
    expires_at bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS native_presentation_recovery_expiry ON certify.native_presentation_recovery(expires_at);
