CREATE TABLE IF NOT EXISTS certify.native_external_issuance (
    id varchar(64) PRIMARY KEY,
    configuration_id varchar(256) NOT NULL,
    content bytea NOT NULL CHECK (octet_length(content) <= 2097152),
    expires_at bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS native_external_issuance_expiry ON certify.native_external_issuance(expires_at);
