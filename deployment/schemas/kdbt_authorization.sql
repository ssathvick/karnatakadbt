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
-- Name: esignet; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA esignet;


--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA public;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: client_detail; Type: TABLE; Schema: esignet; Owner: -
--

CREATE TABLE esignet.client_detail (
    id character varying(100) NOT NULL,
    name character varying(256) NOT NULL,
    rp_id character varying(100) NOT NULL,
    logo_uri character varying(2048) NOT NULL,
    redirect_uris character varying NOT NULL,
    claims character varying NOT NULL,
    acr_values character varying NOT NULL,
    public_key character varying NOT NULL,
    grant_types character varying NOT NULL,
    auth_methods character varying NOT NULL,
    status character varying(20) NOT NULL,
    cr_dtimes timestamp without time zone NOT NULL,
    upd_dtimes timestamp without time zone
);


--
-- Name: consent_detail; Type: TABLE; Schema: esignet; Owner: -
--

CREATE TABLE esignet.consent_detail (
    id uuid NOT NULL,
    client_id character varying NOT NULL,
    psu_token character varying NOT NULL,
    claims character varying NOT NULL,
    authorization_scopes character varying NOT NULL,
    cr_dtimes timestamp without time zone DEFAULT now() NOT NULL,
    expire_dtimes timestamp without time zone,
    signature character varying,
    hash character varying,
    accepted_claims character varying,
    permitted_scopes character varying
);


--
-- Name: consent_history; Type: TABLE; Schema: esignet; Owner: -
--

CREATE TABLE esignet.consent_history (
    id uuid NOT NULL,
    client_id character varying NOT NULL,
    psu_token character varying NOT NULL,
    claims character varying NOT NULL,
    authorization_scopes character varying NOT NULL,
    cr_dtimes timestamp without time zone DEFAULT now() NOT NULL,
    expire_dtimes timestamp without time zone,
    signature character varying,
    hash character varying,
    accepted_claims character varying,
    permitted_scopes character varying
);


--
-- Name: key_alias; Type: TABLE; Schema: esignet; Owner: -
--

CREATE TABLE esignet.key_alias (
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
-- Name: key_policy_def; Type: TABLE; Schema: esignet; Owner: -
--

CREATE TABLE esignet.key_policy_def (
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
-- Name: key_store; Type: TABLE; Schema: esignet; Owner: -
--

CREATE TABLE esignet.key_store (
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
-- Name: public_key_registry; Type: TABLE; Schema: esignet; Owner: -
--

CREATE TABLE esignet.public_key_registry (
    id_hash character varying(100) NOT NULL,
    auth_factor character varying(25) NOT NULL,
    psu_token character varying(256) NOT NULL,
    public_key character varying NOT NULL,
    expire_dtimes timestamp without time zone NOT NULL,
    wallet_binding_id character varying(256) NOT NULL,
    public_key_hash character varying(100) NOT NULL,
    certificate character varying NOT NULL,
    cr_dtimes timestamp without time zone NOT NULL,
    thumbprint character varying NOT NULL
);


--
-- Name: consent_detail consent_detail_pkey; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.consent_detail
    ADD CONSTRAINT consent_detail_pkey PRIMARY KEY (id);


--
-- Name: consent_history consent_history_pkey; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.consent_history
    ADD CONSTRAINT consent_history_pkey PRIMARY KEY (id);


--
-- Name: client_detail pk_clntdtl_id; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.client_detail
    ADD CONSTRAINT pk_clntdtl_id PRIMARY KEY (id);


--
-- Name: key_alias pk_keymals_id; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.key_alias
    ADD CONSTRAINT pk_keymals_id PRIMARY KEY (id);


--
-- Name: key_policy_def pk_keypdef_id; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.key_policy_def
    ADD CONSTRAINT pk_keypdef_id PRIMARY KEY (app_id);


--
-- Name: key_store pk_keystr_id; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.key_store
    ADD CONSTRAINT pk_keystr_id PRIMARY KEY (id);


--
-- Name: public_key_registry pk_public_key_registry; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.public_key_registry
    ADD CONSTRAINT pk_public_key_registry PRIMARY KEY (id_hash, auth_factor);


--
-- Name: client_detail uk_clntdtl_key; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.client_detail
    ADD CONSTRAINT uk_clntdtl_key UNIQUE (public_key);


--
-- Name: key_alias uni_ident_const; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.key_alias
    ADD CONSTRAINT uni_ident_const UNIQUE (uni_ident);


--
-- Name: consent_detail unique_client_token; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.consent_detail
    ADD CONSTRAINT unique_client_token UNIQUE (client_id, psu_token);


--
-- Name: idx_consent_history_psu_client; Type: INDEX; Schema: esignet; Owner: -
--

CREATE INDEX idx_consent_history_psu_client ON esignet.consent_history USING btree (psu_token, client_id);


--
-- Name: idx_consent_psu_client; Type: INDEX; Schema: esignet; Owner: -
--

CREATE INDEX idx_consent_psu_client ON esignet.consent_detail USING btree (psu_token, client_id);


--
-- PostgreSQL database dump complete
--

