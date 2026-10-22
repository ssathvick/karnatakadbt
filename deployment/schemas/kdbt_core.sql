--
-- PostgreSQL database dump
--


-- Dumped from database version 18.6 (Debian 18.6-1.pgdg13+2)
-- Dumped by pg_dump version 18.6 (Debian 18.6-1.pgdg13+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA public;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: beneficiary_batches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.beneficiary_batches (
    id character varying(100) NOT NULL,
    programme_id integer,
    workflow_status character varying(60),
    eligibility_status character varying(60),
    entitlement_status character varying(60),
    instruction_status character varying(60),
    details json NOT NULL
);


--
-- Name: domain_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.domain_events (
    id character varying(100) NOT NULL,
    aggregate character varying(180) NOT NULL,
    action character varying(80) NOT NULL,
    actor character varying(160) NOT NULL,
    payload json NOT NULL,
    at character varying(64) NOT NULL
);


--
-- Name: identifier_ledger; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.identifier_ledger (
    namespace character varying(64) NOT NULL,
    value character varying(32) NOT NULL,
    state character varying(12) NOT NULL,
    created_at character varying(64) NOT NULL,
    issued_at character varying(64)
);


--
-- Name: identifier_namespaces; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.identifier_namespaces (
    name character varying(64) NOT NULL,
    length integer NOT NULL,
    filters json NOT NULL,
    cursor numeric(40,0) NOT NULL,
    "offset" numeric(40,0) NOT NULL,
    multiplier numeric(40,0) NOT NULL
);


--
-- Name: migration_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.migration_records (
    record_key character varying(300) NOT NULL,
    source character varying(60) NOT NULL,
    entity character varying(100) NOT NULL,
    source_id character varying(100) NOT NULL,
    payload json NOT NULL,
    sha256 character varying(64) NOT NULL
);


--
-- Name: programme_applications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.programme_applications (
    id integer NOT NULL,
    subject character varying(160) NOT NULL,
    household_ref character varying(160) NOT NULL,
    programme_id integer NOT NULL,
    status character varying(40) NOT NULL,
    eligibility json,
    version integer NOT NULL,
    updated_at character varying(64) NOT NULL
);


--
-- Name: programmes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.programmes (
    id integer NOT NULL,
    mnemonic character varying(100) NOT NULL,
    name character varying(300) NOT NULL,
    amount_minor bigint NOT NULL,
    income_limit_minor bigint NOT NULL,
    min_members integer NOT NULL,
    status character varying(30) NOT NULL,
    configuration json NOT NULL,
    version integer NOT NULL
);


--
-- Name: programmes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.programmes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: programmes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.programmes_id_seq OWNED BY public.programmes.id;


--
-- Name: projection_outbox; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.projection_outbox (
    key character varying(180) NOT NULL,
    kind character varying(60) NOT NULL,
    payload json NOT NULL,
    status character varying(30) NOT NULL,
    attempts integer NOT NULL,
    error character varying(250),
    updated_at character varying(64) NOT NULL
);


--
-- Name: registry_entities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.registry_entities (
    reference character varying(160) NOT NULL,
    kind character varying(24) NOT NULL,
    name character varying(300) NOT NULL,
    subject character varying(160),
    household_ref character varying(160),
    district_id character varying(64),
    attributes json NOT NULL,
    source_version character varying(100),
    updated_at character varying(64) NOT NULL
);


--
-- Name: programmes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.programmes ALTER COLUMN id SET DEFAULT nextval('public.programmes_id_seq'::regclass);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: beneficiary_batches beneficiary_batches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beneficiary_batches
    ADD CONSTRAINT beneficiary_batches_pkey PRIMARY KEY (id);


--
-- Name: domain_events domain_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.domain_events
    ADD CONSTRAINT domain_events_pkey PRIMARY KEY (id);


--
-- Name: identifier_ledger identifier_ledger_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.identifier_ledger
    ADD CONSTRAINT identifier_ledger_pkey PRIMARY KEY (namespace, value);


--
-- Name: identifier_namespaces identifier_namespaces_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.identifier_namespaces
    ADD CONSTRAINT identifier_namespaces_pkey PRIMARY KEY (name);


--
-- Name: migration_records migration_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.migration_records
    ADD CONSTRAINT migration_records_pkey PRIMARY KEY (record_key);


--
-- Name: programme_applications programme_applications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.programme_applications
    ADD CONSTRAINT programme_applications_pkey PRIMARY KEY (id);


--
-- Name: programme_applications programme_applications_subject_programme_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.programme_applications
    ADD CONSTRAINT programme_applications_subject_programme_id_key UNIQUE (subject, programme_id);


--
-- Name: programmes programmes_mnemonic_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.programmes
    ADD CONSTRAINT programmes_mnemonic_key UNIQUE (mnemonic);


--
-- Name: programmes programmes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.programmes
    ADD CONSTRAINT programmes_pkey PRIMARY KEY (id);


--
-- Name: projection_outbox projection_outbox_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projection_outbox
    ADD CONSTRAINT projection_outbox_pkey PRIMARY KEY (key);


--
-- Name: registry_entities registry_entities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.registry_entities
    ADD CONSTRAINT registry_entities_pkey PRIMARY KEY (reference);


--
-- Name: ix_applications_subject_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_applications_subject_status ON public.programme_applications USING btree (subject, status);


--
-- Name: ix_domain_events_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_domain_events_at ON public.domain_events USING btree (at);


--
-- Name: ix_identifier_ready; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_identifier_ready ON public.identifier_ledger USING btree (namespace, state);


--
-- Name: ix_migration_collection; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_migration_collection ON public.migration_records USING btree (source, entity);


--
-- Name: ix_outbox_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outbox_status ON public.projection_outbox USING btree (status);


--
-- Name: ix_registry_household; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_registry_household ON public.registry_entities USING btree (household_ref);


--
-- Name: ix_registry_kind_subject; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_registry_kind_subject ON public.registry_entities USING btree (kind, subject);


--
-- Name: programme_applications programme_applications_programme_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.programme_applications
    ADD CONSTRAINT programme_applications_programme_id_fkey FOREIGN KEY (programme_id) REFERENCES public.programmes(id);


--
-- PostgreSQL database dump complete
--


