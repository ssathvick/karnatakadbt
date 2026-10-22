-- KarnatakaDBT independent domain schema. Currency amounts are integer paise.


CREATE TABLE beneficiary_batches (
	id VARCHAR(100) NOT NULL, 
	programme_id INTEGER, 
	workflow_status VARCHAR(60), 
	eligibility_status VARCHAR(60), 
	entitlement_status VARCHAR(60), 
	instruction_status VARCHAR(60), 
	details JSON NOT NULL, 
	PRIMARY KEY (id)
)

;


CREATE TABLE domain_events (
	id VARCHAR(100) NOT NULL, 
	aggregate VARCHAR(180) NOT NULL, 
	action VARCHAR(80) NOT NULL, 
	actor VARCHAR(160) NOT NULL, 
	payload JSON NOT NULL, 
	at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE INDEX ix_domain_events_at ON domain_events (at);


CREATE TABLE migration_records (
	record_key VARCHAR(300) NOT NULL, 
	source VARCHAR(60) NOT NULL, 
	entity VARCHAR(100) NOT NULL, 
	source_id VARCHAR(100) NOT NULL, 
	payload JSON NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	PRIMARY KEY (record_key)
)

;

CREATE INDEX ix_migration_collection ON migration_records (source, entity);


CREATE TABLE programmes (
	id SERIAL NOT NULL, 
	mnemonic VARCHAR(100) NOT NULL, 
	name VARCHAR(300) NOT NULL, 
	amount_minor BIGINT NOT NULL, 
	income_limit_minor BIGINT NOT NULL, 
	min_members INTEGER NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	configuration JSON NOT NULL, 
	version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (mnemonic)
)

;


CREATE TABLE projection_outbox (
	key VARCHAR(180) NOT NULL, 
	kind VARCHAR(60) NOT NULL, 
	payload JSON NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	attempts INTEGER NOT NULL, 
	error VARCHAR(250), 
	updated_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (key)
)

;

CREATE INDEX ix_outbox_status ON projection_outbox (status);


CREATE TABLE registry_entities (
	reference VARCHAR(160) NOT NULL, 
	kind VARCHAR(24) NOT NULL, 
	name VARCHAR(300) NOT NULL, 
	subject VARCHAR(160), 
	household_ref VARCHAR(160), 
	district_id VARCHAR(64), 
	attributes JSON NOT NULL, 
	source_version VARCHAR(100), 
	updated_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (reference)
)

;

CREATE INDEX ix_registry_household ON registry_entities (household_ref);

CREATE INDEX ix_registry_kind_subject ON registry_entities (kind, subject);


CREATE TABLE programme_applications (
	id INTEGER NOT NULL, 
	subject VARCHAR(160) NOT NULL, 
	household_ref VARCHAR(160) NOT NULL, 
	programme_id INTEGER NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	eligibility JSON, 
	version INTEGER NOT NULL, 
	updated_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (subject, programme_id), 
	FOREIGN KEY(programme_id) REFERENCES programmes (id)
)

;

CREATE INDEX ix_applications_subject_status ON programme_applications (subject, status);