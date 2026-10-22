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

SET default_table_access_method = heap;

--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    entity_type character varying(50) NOT NULL,
    entity_id character varying NOT NULL,
    action character varying(50) NOT NULL,
    actor character varying(255) NOT NULL,
    details jsonb,
    id character varying NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone
);


--
-- Name: auth_contexts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_contexts (
    consent_request_id character varying NOT NULL,
    auth_provider character varying(255),
    auth_method character varying(50),
    auth_timestamp timestamp with time zone,
    issuer character varying(512),
    id_token_hash character varying(128) NOT NULL,
    token_validated boolean NOT NULL,
    verified_claims jsonb NOT NULL,
    id character varying NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone
);


--
-- Name: cm_awe_processed_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cm_awe_processed_events (
    event_id character varying(64) NOT NULL,
    event_type character varying(64) NOT NULL,
    request_id character varying(64) NOT NULL,
    processed_at timestamp with time zone NOT NULL,
    note text,
    id character varying NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone
);


--
-- Name: consent_artefacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.consent_artefacts (
    subject_id_type character varying(50) NOT NULL,
    subject_id_value character varying(255) NOT NULL,
    controller_id character varying(255) NOT NULL,
    partner_id character varying NOT NULL,
    purpose jsonb NOT NULL,
    data_scopes jsonb NOT NULL,
    effective_data_scopes jsonb NOT NULL,
    fetch_type character varying(20) NOT NULL,
    valid_from timestamp with time zone NOT NULL,
    valid_until timestamp with time zone NOT NULL,
    source character varying(20) NOT NULL,
    policy_version integer,
    auth_context_id character varying,
    object_jti character varying(255),
    status character varying(20) NOT NULL,
    revoked_at timestamp with time zone,
    expired_at timestamp with time zone,
    id character varying NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone
);


--
-- Name: consent_receipts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.consent_receipts (
    consent_id character varying NOT NULL,
    artefact_hash character varying(128) NOT NULL,
    algorithm character varying(20) NOT NULL,
    kid character varying(255) NOT NULL,
    signature text NOT NULL,
    version character varying(16) NOT NULL,
    document jsonb NOT NULL,
    id character varying NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone
);


--
-- Name: consent_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.consent_requests (
    subject_id_type character varying(50) NOT NULL,
    subject_id_value character varying(255) NOT NULL,
    controller_id character varying(255) NOT NULL,
    partner_id character varying NOT NULL,
    purpose jsonb NOT NULL,
    requested_scopes jsonb NOT NULL,
    valid_from timestamp with time zone,
    valid_until timestamp with time zone,
    status character varying(20) NOT NULL,
    id character varying NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone
);


--
-- Name: decision_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.decision_logs (
    partner_id character varying,
    consent_id character varying,
    object_jti character varying(255),
    decision character varying(10) NOT NULL,
    reason_code character varying(40) NOT NULL,
    detail text,
    policy_version integer,
    request_ctx_hash character varying(128),
    id character varying NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone
);


--
-- Name: partner_policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.partner_policies (
    partner_id character varying NOT NULL,
    version integer NOT NULL,
    status character varying(20) NOT NULL,
    allowed_data_scopes jsonb NOT NULL,
    allowed_purposes jsonb NOT NULL,
    allowed_subject_id_types jsonb NOT NULL,
    allowed_signing_algs jsonb NOT NULL,
    max_validity_duration character varying(32),
    fetch_type character varying(20) NOT NULL,
    max_fetch_frequency character varying(32),
    data_life character varying(32),
    awe_request_id character varying(64),
    effective_from timestamp with time zone,
    id character varying NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone
);


--
-- Name: partners; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.partners (
    name character varying(255),
    audience character varying(255) NOT NULL,
    controller_id character varying(255) NOT NULL,
    status character varying(20) NOT NULL,
    partner_mgmt_id character varying(255),
    id character varying NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone
);


--
-- Name: revocation_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.revocation_records (
    consent_id character varying NOT NULL,
    originated_by character varying(20) NOT NULL,
    reason text,
    id character varying NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone
);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: auth_contexts auth_contexts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_contexts
    ADD CONSTRAINT auth_contexts_pkey PRIMARY KEY (id);


--
-- Name: cm_awe_processed_events cm_awe_processed_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cm_awe_processed_events
    ADD CONSTRAINT cm_awe_processed_events_pkey PRIMARY KEY (id);


--
-- Name: consent_artefacts consent_artefacts_object_jti_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consent_artefacts
    ADD CONSTRAINT consent_artefacts_object_jti_key UNIQUE (object_jti);


--
-- Name: consent_artefacts consent_artefacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consent_artefacts
    ADD CONSTRAINT consent_artefacts_pkey PRIMARY KEY (id);


--
-- Name: consent_receipts consent_receipts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consent_receipts
    ADD CONSTRAINT consent_receipts_pkey PRIMARY KEY (id);


--
-- Name: consent_requests consent_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consent_requests
    ADD CONSTRAINT consent_requests_pkey PRIMARY KEY (id);


--
-- Name: decision_logs decision_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.decision_logs
    ADD CONSTRAINT decision_logs_pkey PRIMARY KEY (id);


--
-- Name: partner_policies partner_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.partner_policies
    ADD CONSTRAINT partner_policies_pkey PRIMARY KEY (id);


--
-- Name: partners partners_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.partners
    ADD CONSTRAINT partners_pkey PRIMARY KEY (id);


--
-- Name: revocation_records revocation_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.revocation_records
    ADD CONSTRAINT revocation_records_pkey PRIMARY KEY (id);


--
-- Name: partner_policies uq_partner_policy_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.partner_policies
    ADD CONSTRAINT uq_partner_policy_version UNIQUE (partner_id, version);


--
-- Name: ix_audit_logs_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_entity ON public.audit_logs USING btree (entity_type, entity_id);


--
-- Name: ix_auth_contexts_consent_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_auth_contexts_consent_request_id ON public.auth_contexts USING btree (consent_request_id);


--
-- Name: ix_cm_awe_processed_events_event_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_cm_awe_processed_events_event_id ON public.cm_awe_processed_events USING btree (event_id);


--
-- Name: ix_cm_awe_processed_events_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cm_awe_processed_events_request_id ON public.cm_awe_processed_events USING btree (request_id);


--
-- Name: ix_consent_artefacts_controller_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_consent_artefacts_controller_id ON public.consent_artefacts USING btree (controller_id);


--
-- Name: ix_consent_artefacts_partner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_consent_artefacts_partner_id ON public.consent_artefacts USING btree (partner_id);


--
-- Name: ix_consent_artefacts_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_consent_artefacts_status ON public.consent_artefacts USING btree (status);


--
-- Name: ix_consent_artefacts_subject_id_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_consent_artefacts_subject_id_type ON public.consent_artefacts USING btree (subject_id_type);


--
-- Name: ix_consent_artefacts_subject_id_value; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_consent_artefacts_subject_id_value ON public.consent_artefacts USING btree (subject_id_value);


--
-- Name: ix_consent_artefacts_valid_until; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_consent_artefacts_valid_until ON public.consent_artefacts USING btree (valid_until);


--
-- Name: ix_consent_receipts_consent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_consent_receipts_consent_id ON public.consent_receipts USING btree (consent_id);


--
-- Name: ix_consent_requests_controller_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_consent_requests_controller_id ON public.consent_requests USING btree (controller_id);


--
-- Name: ix_consent_requests_partner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_consent_requests_partner_id ON public.consent_requests USING btree (partner_id);


--
-- Name: ix_consent_requests_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_consent_requests_status ON public.consent_requests USING btree (status);


--
-- Name: ix_consent_requests_subject_id_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_consent_requests_subject_id_type ON public.consent_requests USING btree (subject_id_type);


--
-- Name: ix_consent_requests_subject_id_value; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_consent_requests_subject_id_value ON public.consent_requests USING btree (subject_id_value);


--
-- Name: ix_decision_logs_consent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_decision_logs_consent ON public.decision_logs USING btree (consent_id);


--
-- Name: ix_decision_logs_partner_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_decision_logs_partner_created ON public.decision_logs USING btree (partner_id, created_at);


--
-- Name: ix_partner_policies_awe_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_partner_policies_awe_request_id ON public.partner_policies USING btree (awe_request_id);


--
-- Name: ix_partner_policies_partner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_partner_policies_partner_id ON public.partner_policies USING btree (partner_id);


--
-- Name: ix_partners_audience; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_partners_audience ON public.partners USING btree (audience);


--
-- Name: ix_partners_controller_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_partners_controller_id ON public.partners USING btree (controller_id);


--
-- Name: ix_partners_partner_mgmt_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_partners_partner_mgmt_id ON public.partners USING btree (partner_mgmt_id);


--
-- Name: ix_revocation_records_consent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_revocation_records_consent_id ON public.revocation_records USING btree (consent_id);


--
-- PostgreSQL database dump complete
--

