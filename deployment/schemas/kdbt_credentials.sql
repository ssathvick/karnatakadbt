--
-- PostgreSQL database dump
--

-- Dumped from database version 16.4
-- Dumped by pg_dump version 16.4

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: certify; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA certify;


--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA public;


--
-- Name: credential_status_enum; Type: TYPE; Schema: certify; Owner: -
--

CREATE TYPE certify.credential_status_enum AS ENUM (
    'AVAILABLE',
    'FULL'
);


--
-- Name: kdbt_status_capacity_compatibility(); Type: FUNCTION; Schema: certify; Owner: -
--

CREATE FUNCTION certify.kdbt_status_capacity_compatibility() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF TG_OP='UPDATE' THEN
  IF NEW.capacity IS DISTINCT FROM OLD.capacity AND NEW.capacity_in_kb IS NOT DISTINCT FROM OLD.capacity_in_kb THEN
   NEW.capacity_in_kb := NULL;
  ELSIF NEW.capacity_in_kb IS DISTINCT FROM OLD.capacity_in_kb AND NEW.capacity IS NOT DISTINCT FROM OLD.capacity THEN
   NEW.capacity := NULL;
  END IF;
 END IF;
 IF NEW.capacity IS NULL AND NEW.capacity_in_kb IS NOT NULL THEN
  IF NEW.capacity_in_kb<1 OR NEW.capacity_in_kb>1024 THEN RAISE EXCEPTION 'Unsupported status capacity'; END IF;
  NEW.capacity := NEW.capacity_in_kb*8192;
 ELSIF NEW.capacity_in_kb IS NULL AND NEW.capacity IS NOT NULL THEN
  IF NEW.capacity<8192 OR NEW.capacity>8388608 OR NEW.capacity%8192<>0 THEN RAISE EXCEPTION 'Unsupported status capacity'; END IF;
  NEW.capacity_in_kb := NEW.capacity/8192;
 END IF;
 IF NEW.capacity IS NULL OR NEW.capacity_in_kb IS NULL OR NEW.capacity<>NEW.capacity_in_kb*8192
    OR NEW.capacity_in_kb<1 OR NEW.capacity_in_kb>1024 THEN
  RAISE EXCEPTION 'Conflicting status capacity units';
 END IF;
 NEW.credential_status := COALESCE(NEW.credential_status,'AVAILABLE');
 RETURN NEW;
END $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: ca_cert_store; Type: TABLE; Schema: certify; Owner: -
--

CREATE TABLE certify.ca_cert_store (
    cert_id character varying(36) NOT NULL,
    cert_subject character varying(500) NOT NULL,
    cert_issuer character varying(500) NOT NULL,
    issuer_id character varying(36) NOT NULL,
    cert_not_before timestamp without time zone,
    cert_not_after timestamp without time zone,
    crl_uri character varying(120),
    cert_data character varying,
    cert_thumbprint character varying(100),
    cert_serial_no character varying(50),
    partner_domain character varying(36),
    cr_by character varying(256),
    cr_dtimes timestamp without time zone,
    upd_by character varying(256),
    upd_dtimes timestamp without time zone,
    is_deleted boolean DEFAULT false,
    del_dtimes timestamp without time zone,
    ca_cert_type character varying(25)
);


--
-- Name: credential_config; Type: TABLE; Schema: certify; Owner: -
--

CREATE TABLE certify.credential_config (
    credential_config_key_id character varying(2048) NOT NULL,
    config_id character varying(255) NOT NULL,
    status character varying(255),
    vc_template character varying,
    doctype character varying,
    sd_jwt_vct character varying,
    context character varying,
    credential_type character varying,
    credential_format character varying(255) NOT NULL,
    did_url character varying,
    key_manager_app_id character varying(36),
    key_manager_ref_id character varying(128),
    signature_algo character varying(36),
    signature_crypto_suite character varying(128),
    sd_claim character varying,
    display jsonb NOT NULL,
    display_order text[] NOT NULL,
    scope character varying(255) NOT NULL,
    cryptographic_binding_methods_supported text[] NOT NULL,
    credential_signing_alg_values_supported text[] NOT NULL,
    proof_types_supported jsonb NOT NULL,
    credential_subject jsonb,
    sd_jwt_claims jsonb,
    mso_mdoc_claims jsonb,
    plugin_configurations jsonb,
    credential_status_purpose text[],
    qr_settings jsonb,
    qr_signature_algo text,
    cr_dtimes timestamp without time zone NOT NULL,
    upd_dtimes timestamp without time zone
);


--
-- Name: credential_status_transaction; Type: TABLE; Schema: certify; Owner: -
--

CREATE TABLE certify.credential_status_transaction (
    transaction_log_id integer NOT NULL,
    credential_id character varying(255),
    status_purpose character varying(100),
    status_value boolean,
    status_list_credential_id character varying(255),
    status_list_index bigint,
    cr_dtimes timestamp without time zone DEFAULT now() NOT NULL,
    processed_dtimes timestamp without time zone,
    is_processed boolean DEFAULT false NOT NULL
);


--
-- Name: credential_status_transaction_transaction_log_id_seq; Type: SEQUENCE; Schema: certify; Owner: -
--

CREATE SEQUENCE certify.credential_status_transaction_transaction_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: credential_status_transaction_transaction_log_id_seq; Type: SEQUENCE OWNED BY; Schema: certify; Owner: -
--

ALTER SEQUENCE certify.credential_status_transaction_transaction_log_id_seq OWNED BY certify.credential_status_transaction.transaction_log_id;


--
-- Name: iar_session; Type: TABLE; Schema: certify; Owner: -
--

CREATE TABLE certify.iar_session (
    id integer NOT NULL,
    auth_session character varying(128) NOT NULL,
    transaction_id character varying(64) NOT NULL,
    request_id character varying(64),
    verify_nonce character varying(64),
    expires_at timestamp without time zone NOT NULL,
    client_id character varying(128),
    scope character varying(128),
    authorization_code character varying(128),
    response_uri character varying(512),
    code_challenge character varying(128),
    code_challenge_method character varying(10),
    code_issued_at timestamp without time zone,
    is_code_used boolean DEFAULT false NOT NULL,
    code_used_at timestamp without time zone,
    cr_dtimes timestamp without time zone DEFAULT now() NOT NULL,
    identity_data text
);


--
-- Name: iar_session_id_seq; Type: SEQUENCE; Schema: certify; Owner: -
--

CREATE SEQUENCE certify.iar_session_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: iar_session_id_seq; Type: SEQUENCE OWNED BY; Schema: certify; Owner: -
--

ALTER SEQUENCE certify.iar_session_id_seq OWNED BY certify.iar_session.id;


--
-- Name: key_alias; Type: TABLE; Schema: certify; Owner: -
--

CREATE TABLE certify.key_alias (
    id character varying(36) NOT NULL,
    app_id character varying(36) NOT NULL,
    ref_id character varying(128),
    key_gen_dtimes timestamp without time zone,
    key_expire_dtimes timestamp without time zone,
    status_code character varying(36),
    lang_code character varying(3),
    cr_by character varying(256) NOT NULL,
    cr_dtimes timestamp without time zone NOT NULL,
    upd_by character varying(256),
    upd_dtimes timestamp without time zone,
    is_deleted boolean DEFAULT false,
    del_dtimes timestamp without time zone,
    cert_thumbprint character varying(100),
    uni_ident character varying(50)
);


--
-- Name: key_policy_def; Type: TABLE; Schema: certify; Owner: -
--

CREATE TABLE certify.key_policy_def (
    app_id character varying(36) NOT NULL,
    key_validity_duration smallint,
    is_active boolean NOT NULL,
    pre_expire_days smallint,
    access_allowed character varying(1024),
    cr_by character varying(256) NOT NULL,
    cr_dtimes timestamp without time zone NOT NULL,
    upd_by character varying(256),
    upd_dtimes timestamp without time zone,
    is_deleted boolean DEFAULT false,
    del_dtimes timestamp without time zone
);


--
-- Name: key_store; Type: TABLE; Schema: certify; Owner: -
--

CREATE TABLE certify.key_store (
    id character varying(36) NOT NULL,
    master_key character varying(36) NOT NULL,
    private_key character varying(2500) NOT NULL,
    certificate_data character varying NOT NULL,
    cr_by character varying(256) NOT NULL,
    cr_dtimes timestamp without time zone NOT NULL,
    upd_by character varying(256),
    upd_dtimes timestamp without time zone,
    is_deleted boolean DEFAULT false,
    del_dtimes timestamp without time zone
);


--
-- Name: ledger; Type: TABLE; Schema: certify; Owner: -
--

CREATE TABLE certify.ledger (
    id integer NOT NULL,
    credential_id character varying(255),
    issuer_id character varying(255) NOT NULL,
    issuance_date timestamp without time zone NOT NULL,
    expiration_date timestamp without time zone,
    credential_type character varying(100) NOT NULL,
    indexed_attributes jsonb,
    credential_status_details jsonb DEFAULT '[]'::jsonb NOT NULL,
    cr_dtimes timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT ensure_credential_status_details_is_array CHECK ((jsonb_typeof(credential_status_details) = 'array'::text))
);


--
-- Name: ledger_id_seq; Type: SEQUENCE; Schema: certify; Owner: -
--

CREATE SEQUENCE certify.ledger_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ledger_id_seq; Type: SEQUENCE OWNED BY; Schema: certify; Owner: -
--

ALTER SEQUENCE certify.ledger_id_seq OWNED BY certify.ledger.id;


--
-- Name: native_authorization; Type: TABLE; Schema: certify; Owner: -
--

CREATE TABLE certify.native_authorization (
    id text NOT NULL,
    offer_hash text,
    kind text NOT NULL,
    content bytea NOT NULL,
    expires_at bigint NOT NULL,
    used_at bigint,
    tx_salt bytea,
    tx_hash bytea,
    attempts integer DEFAULT 0 NOT NULL,
    CONSTRAINT native_authorization_kind_check CHECK ((kind = ANY (ARRAY['PREAUTH'::text, 'IAR'::text])))
);


--
-- Name: native_credential_session; Type: TABLE; Schema: certify; Owner: -
--

CREATE TABLE certify.native_credential_session (
    id text NOT NULL,
    content bytea NOT NULL,
    expires_at bigint NOT NULL
);


--
-- Name: native_external_issuance; Type: TABLE; Schema: certify; Owner: -
--

CREATE TABLE certify.native_external_issuance (
    id character varying(64) NOT NULL,
    configuration_id character varying(256) NOT NULL,
    content bytea NOT NULL,
    expires_at bigint NOT NULL,
    CONSTRAINT native_external_issuance_content_check CHECK ((octet_length(content) <= 2097152))
);


--
-- Name: native_presentation_recovery; Type: TABLE; Schema: certify; Owner: -
--

CREATE TABLE certify.native_presentation_recovery (
    id text NOT NULL,
    kind text NOT NULL,
    content bytea NOT NULL,
    expires_at bigint NOT NULL,
    CONSTRAINT native_presentation_recovery_content_check CHECK ((octet_length(content) <= 1048576)),
    CONSTRAINT native_presentation_recovery_id_check CHECK ((length(id) = 64)),
    CONSTRAINT native_presentation_recovery_kind_check CHECK ((kind = ANY (ARRAY['VP_RECOVERY'::text, 'VP_RECOVERY_INDEX'::text])))
);


--
-- Name: rendering_template; Type: TABLE; Schema: certify; Owner: -
--

CREATE TABLE certify.rendering_template (
    id character varying(128) NOT NULL,
    template character varying NOT NULL,
    cr_dtimes timestamp without time zone NOT NULL,
    upd_dtimes timestamp without time zone
);


--
-- Name: shedlock; Type: TABLE; Schema: certify; Owner: -
--

CREATE TABLE certify.shedlock (
    name character varying(64) NOT NULL,
    lock_until timestamp(3) with time zone NOT NULL,
    locked_at timestamp(3) with time zone NOT NULL,
    locked_by character varying(255) NOT NULL
);


--
-- Name: status_list_available_indices; Type: TABLE; Schema: certify; Owner: -
--

CREATE TABLE certify.status_list_available_indices (
    id integer NOT NULL,
    status_list_credential_id character varying(255) NOT NULL,
    list_index bigint NOT NULL,
    is_assigned boolean DEFAULT false NOT NULL,
    cr_dtimes timestamp without time zone DEFAULT now() NOT NULL,
    upd_dtimes timestamp without time zone
);


--
-- Name: status_list_available_indices_id_seq; Type: SEQUENCE; Schema: certify; Owner: -
--

CREATE SEQUENCE certify.status_list_available_indices_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: status_list_available_indices_id_seq; Type: SEQUENCE OWNED BY; Schema: certify; Owner: -
--

ALTER SEQUENCE certify.status_list_available_indices_id_seq OWNED BY certify.status_list_available_indices.id;


--
-- Name: status_list_credential; Type: TABLE; Schema: certify; Owner: -
--

CREATE TABLE certify.status_list_credential (
    id character varying(255) NOT NULL,
    vc_document character varying NOT NULL,
    credential_type character varying(100) NOT NULL,
    status_purpose character varying(100),
    capacity bigint,
    credential_status certify.credential_status_enum,
    cr_dtimes timestamp without time zone DEFAULT now() NOT NULL,
    upd_dtimes timestamp without time zone,
    capacity_in_kb bigint
);


--
-- Name: credential_status_transaction transaction_log_id; Type: DEFAULT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.credential_status_transaction ALTER COLUMN transaction_log_id SET DEFAULT nextval('certify.credential_status_transaction_transaction_log_id_seq'::regclass);


--
-- Name: iar_session id; Type: DEFAULT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.iar_session ALTER COLUMN id SET DEFAULT nextval('certify.iar_session_id_seq'::regclass);


--
-- Name: ledger id; Type: DEFAULT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.ledger ALTER COLUMN id SET DEFAULT nextval('certify.ledger_id_seq'::regclass);


--
-- Name: status_list_available_indices id; Type: DEFAULT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.status_list_available_indices ALTER COLUMN id SET DEFAULT nextval('certify.status_list_available_indices_id_seq'::regclass);


--
-- Name: ca_cert_store cert_thumbprint_unique; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.ca_cert_store
    ADD CONSTRAINT cert_thumbprint_unique UNIQUE (cert_thumbprint, partner_domain);


--
-- Name: credential_config credential_config_credential_config_key_id_key; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.credential_config
    ADD CONSTRAINT credential_config_credential_config_key_id_key UNIQUE (credential_config_key_id);


--
-- Name: credential_status_transaction credential_status_transaction_pkey; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.credential_status_transaction
    ADD CONSTRAINT credential_status_transaction_pkey PRIMARY KEY (transaction_log_id);


--
-- Name: iar_session iar_session_auth_session_key; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.iar_session
    ADD CONSTRAINT iar_session_auth_session_key UNIQUE (auth_session);


--
-- Name: iar_session iar_session_authorization_code_key; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.iar_session
    ADD CONSTRAINT iar_session_authorization_code_key UNIQUE (authorization_code);


--
-- Name: iar_session iar_session_pkey; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.iar_session
    ADD CONSTRAINT iar_session_pkey PRIMARY KEY (id);


--
-- Name: ledger ledger_pkey; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.ledger
    ADD CONSTRAINT ledger_pkey PRIMARY KEY (id);


--
-- Name: native_authorization native_authorization_offer_hash_key; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.native_authorization
    ADD CONSTRAINT native_authorization_offer_hash_key UNIQUE (offer_hash);


--
-- Name: native_authorization native_authorization_pkey; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.native_authorization
    ADD CONSTRAINT native_authorization_pkey PRIMARY KEY (id);


--
-- Name: native_credential_session native_credential_session_pkey; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.native_credential_session
    ADD CONSTRAINT native_credential_session_pkey PRIMARY KEY (id);


--
-- Name: native_external_issuance native_external_issuance_pkey; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.native_external_issuance
    ADD CONSTRAINT native_external_issuance_pkey PRIMARY KEY (id);


--
-- Name: native_presentation_recovery native_presentation_recovery_pkey; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.native_presentation_recovery
    ADD CONSTRAINT native_presentation_recovery_pkey PRIMARY KEY (id);


--
-- Name: ca_cert_store pk_cacs_id; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.ca_cert_store
    ADD CONSTRAINT pk_cacs_id PRIMARY KEY (cert_id);


--
-- Name: credential_config pk_config_id; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.credential_config
    ADD CONSTRAINT pk_config_id PRIMARY KEY (config_id);


--
-- Name: key_alias pk_keymals_id; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.key_alias
    ADD CONSTRAINT pk_keymals_id PRIMARY KEY (id);


--
-- Name: key_policy_def pk_keypdef_id; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.key_policy_def
    ADD CONSTRAINT pk_keypdef_id PRIMARY KEY (app_id);


--
-- Name: key_store pk_keystr_id; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.key_store
    ADD CONSTRAINT pk_keystr_id PRIMARY KEY (id);


--
-- Name: rendering_template pk_svgtmp_id; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.rendering_template
    ADD CONSTRAINT pk_svgtmp_id PRIMARY KEY (id);


--
-- Name: shedlock shedlock_pkey; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.shedlock
    ADD CONSTRAINT shedlock_pkey PRIMARY KEY (name);


--
-- Name: status_list_available_indices status_list_available_indices_pkey; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.status_list_available_indices
    ADD CONSTRAINT status_list_available_indices_pkey PRIMARY KEY (id);


--
-- Name: status_list_credential status_list_credential_pkey; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.status_list_credential
    ADD CONSTRAINT status_list_credential_pkey PRIMARY KEY (id);


--
-- Name: key_alias uni_ident_const; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.key_alias
    ADD CONSTRAINT uni_ident_const UNIQUE (uni_ident);


--
-- Name: ledger uq_ledger_tracked_credential_id; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.ledger
    ADD CONSTRAINT uq_ledger_tracked_credential_id UNIQUE (credential_id);


--
-- Name: status_list_available_indices uq_list_id_and_index; Type: CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.status_list_available_indices
    ADD CONSTRAINT uq_list_id_and_index UNIQUE (status_list_credential_id, list_index);


--
-- Name: idx_credential_config_doctype_unique; Type: INDEX; Schema: certify; Owner: -
--

CREATE UNIQUE INDEX idx_credential_config_doctype_unique ON certify.credential_config USING btree (doctype, credential_format) WHERE ((doctype IS NOT NULL) AND ((doctype)::text <> ''::text));


--
-- Name: idx_credential_config_sd_jwt_vct_unique; Type: INDEX; Schema: certify; Owner: -
--

CREATE UNIQUE INDEX idx_credential_config_sd_jwt_vct_unique ON certify.credential_config USING btree (sd_jwt_vct, credential_format) WHERE ((sd_jwt_vct IS NOT NULL) AND ((sd_jwt_vct)::text <> ''::text));


--
-- Name: idx_credential_config_type_context_unique; Type: INDEX; Schema: certify; Owner: -
--

CREATE UNIQUE INDEX idx_credential_config_type_context_unique ON certify.credential_config USING btree (credential_type, context, credential_format) WHERE ((credential_type IS NOT NULL) AND ((credential_type)::text <> ''::text) AND (context IS NOT NULL) AND ((context)::text <> ''::text));


--
-- Name: idx_cst_is_processed_created; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_cst_is_processed_created ON certify.credential_status_transaction USING btree (is_processed, cr_dtimes);


--
-- Name: idx_gin_ledger_indexed_attrs; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_gin_ledger_indexed_attrs ON certify.ledger USING gin (indexed_attributes);


--
-- Name: idx_gin_ledger_status_details; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_gin_ledger_status_details ON certify.ledger USING gin (credential_status_details);


--
-- Name: idx_iar_session_auth_session; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_iar_session_auth_session ON certify.iar_session USING btree (auth_session);


--
-- Name: idx_iar_session_authorization_code; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_iar_session_authorization_code ON certify.iar_session USING btree (authorization_code);


--
-- Name: idx_iar_session_authorization_code_used; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_iar_session_authorization_code_used ON certify.iar_session USING btree (authorization_code, is_code_used) WHERE (authorization_code IS NOT NULL);


--
-- Name: idx_iar_session_expires_at; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_iar_session_expires_at ON certify.iar_session USING btree (expires_at);


--
-- Name: idx_iar_session_request_id; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_iar_session_request_id ON certify.iar_session USING btree (request_id);


--
-- Name: idx_iar_session_scope; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_iar_session_scope ON certify.iar_session USING btree (scope);


--
-- Name: idx_iar_session_transaction_id; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_iar_session_transaction_id ON certify.iar_session USING btree (transaction_id);


--
-- Name: idx_ledger_cr_dtimes; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_ledger_cr_dtimes ON certify.ledger USING btree (cr_dtimes);


--
-- Name: idx_ledger_credential_id; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_ledger_credential_id ON certify.ledger USING btree (credential_id);


--
-- Name: idx_ledger_credential_type; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_ledger_credential_type ON certify.ledger USING btree (credential_type);


--
-- Name: idx_ledger_expiration_date; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_ledger_expiration_date ON certify.ledger USING btree (expiration_date);


--
-- Name: idx_ledger_issuance_date; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_ledger_issuance_date ON certify.ledger USING btree (issuance_date);


--
-- Name: idx_ledger_issuer_id; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_ledger_issuer_id ON certify.ledger USING btree (issuer_id);


--
-- Name: idx_sla_available_indices; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_sla_available_indices ON certify.status_list_available_indices USING btree (status_list_credential_id, is_assigned, list_index) WHERE (is_assigned = false);


--
-- Name: idx_sla_cr_dtimes; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_sla_cr_dtimes ON certify.status_list_available_indices USING btree (cr_dtimes);


--
-- Name: idx_sla_is_assigned; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_sla_is_assigned ON certify.status_list_available_indices USING btree (is_assigned);


--
-- Name: idx_sla_list_index; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_sla_list_index ON certify.status_list_available_indices USING btree (list_index);


--
-- Name: idx_sla_status_list_credential_id; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_sla_status_list_credential_id ON certify.status_list_available_indices USING btree (status_list_credential_id);


--
-- Name: idx_slc_cr_dtimes; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_slc_cr_dtimes ON certify.status_list_credential USING btree (cr_dtimes);


--
-- Name: idx_slc_credential_status; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_slc_credential_status ON certify.status_list_credential USING btree (credential_status);


--
-- Name: idx_slc_credential_type; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_slc_credential_type ON certify.status_list_credential USING btree (credential_type);


--
-- Name: idx_slc_status_purpose; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX idx_slc_status_purpose ON certify.status_list_credential USING btree (status_purpose);


--
-- Name: native_external_issuance_expiry; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX native_external_issuance_expiry ON certify.native_external_issuance USING btree (expires_at);


--
-- Name: native_presentation_recovery_expiry; Type: INDEX; Schema: certify; Owner: -
--

CREATE INDEX native_presentation_recovery_expiry ON certify.native_presentation_recovery USING btree (expires_at);


--
-- Name: status_list_credential kdbt_status_capacity_compatibility; Type: TRIGGER; Schema: certify; Owner: -
--



--
-- Name: status_list_available_indices fk_status_list_credential; Type: FK CONSTRAINT; Schema: certify; Owner: -
--

ALTER TABLE ONLY certify.status_list_available_indices
    ADD CONSTRAINT fk_status_list_credential FOREIGN KEY (status_list_credential_id) REFERENCES certify.status_list_credential(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

