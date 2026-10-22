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
-- Name: pm_audit_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pm_audit_events (
    actor_id character varying(255),
    actor_name character varying(255),
    action character varying(40) NOT NULL,
    entity_type character varying(32) NOT NULL,
    entity_id character varying(64),
    partner_id character varying(255) NOT NULL,
    request_id character varying(64),
    details jsonb NOT NULL,
    id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: pm_partner_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pm_partner_keys (
    partner_id character varying(255) NOT NULL,
    kid character varying(255) NOT NULL,
    algorithm character varying(20) NOT NULL,
    public_key text NOT NULL,
    key_fingerprint character varying(128),
    status character varying(20) NOT NULL,
    not_before timestamp with time zone,
    not_after timestamp with time zone,
    id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: pm_partner_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pm_partner_requests (
    request_type character varying(20) NOT NULL,
    partner_id character varying(255) NOT NULL,
    name character varying(255),
    org_name character varying(255),
    description text,
    jwks_url character varying(1024),
    proposed_keys jsonb NOT NULL,
    revoke_kids jsonb NOT NULL,
    status character varying(20) NOT NULL,
    submitted_by character varying(255),
    reviewed_by character varying(255),
    review_notes text,
    awe_request_id character varying(64),
    id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: pm_partners; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pm_partners (
    partner_id character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    org_name character varying(255),
    description text,
    jwks_url character varying(1024),
    status character varying(20) NOT NULL,
    created_by character varying(255),
    approved_by character varying(255),
    id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: pm_audit_events pm_audit_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pm_audit_events
    ADD CONSTRAINT pm_audit_events_pkey PRIMARY KEY (id);


--
-- Name: pm_partner_keys pm_partner_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pm_partner_keys
    ADD CONSTRAINT pm_partner_keys_pkey PRIMARY KEY (id);


--
-- Name: pm_partner_requests pm_partner_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pm_partner_requests
    ADD CONSTRAINT pm_partner_requests_pkey PRIMARY KEY (id);


--
-- Name: pm_partners pm_partners_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pm_partners
    ADD CONSTRAINT pm_partners_pkey PRIMARY KEY (id);


--
-- Name: pm_partner_keys uq_pm_partner_kid; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pm_partner_keys
    ADD CONSTRAINT uq_pm_partner_kid UNIQUE (partner_id, kid);


--
-- Name: ix_pm_audit_events_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pm_audit_events_action ON public.pm_audit_events USING btree (action);


--
-- Name: ix_pm_audit_events_partner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pm_audit_events_partner_id ON public.pm_audit_events USING btree (partner_id);


--
-- Name: ix_pm_partner_keys_key_fingerprint; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pm_partner_keys_key_fingerprint ON public.pm_partner_keys USING btree (key_fingerprint);


--
-- Name: ix_pm_partner_keys_kid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pm_partner_keys_kid ON public.pm_partner_keys USING btree (kid);


--
-- Name: ix_pm_partner_keys_partner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pm_partner_keys_partner_id ON public.pm_partner_keys USING btree (partner_id);


--
-- Name: ix_pm_partner_keys_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pm_partner_keys_status ON public.pm_partner_keys USING btree (status);


--
-- Name: ix_pm_partner_requests_awe_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pm_partner_requests_awe_request_id ON public.pm_partner_requests USING btree (awe_request_id);


--
-- Name: ix_pm_partner_requests_partner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pm_partner_requests_partner_id ON public.pm_partner_requests USING btree (partner_id);


--
-- Name: ix_pm_partner_requests_request_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pm_partner_requests_request_type ON public.pm_partner_requests USING btree (request_type);


--
-- Name: ix_pm_partner_requests_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pm_partner_requests_status ON public.pm_partner_requests USING btree (status);


--
-- Name: ix_pm_partners_partner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_pm_partners_partner_id ON public.pm_partners USING btree (partner_id);


--
-- Name: ix_pm_partners_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pm_partners_status ON public.pm_partners USING btree (status);


--
-- PostgreSQL database dump complete
--

