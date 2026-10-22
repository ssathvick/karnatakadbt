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
-- Name: native_approval_live_20261018034134; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA native_approval_live_20261018034134;


--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA public;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: native_approval_audit; Type: TABLE; Schema: native_approval_live_20261018034134; Owner: -
--

CREATE TABLE native_approval_live_20261018034134.native_approval_audit (
    id character varying(36) NOT NULL,
    actor character varying(128) NOT NULL,
    action character varying(64) NOT NULL,
    resource_id character varying(180) NOT NULL,
    at character varying NOT NULL,
    before json,
    after json,
    actor_email character varying(255),
    resource_type character varying(32) NOT NULL,
    summary character varying,
    metadata json
);


--
-- Name: native_approval_objects; Type: TABLE; Schema: native_approval_live_20261018034134; Owner: -
--

CREATE TABLE native_approval_live_20261018034134.native_approval_objects (
    id character varying(180) NOT NULL,
    kind character varying(24) NOT NULL,
    parent character varying(180),
    status character varying(24),
    actor character varying(128),
    at character varying NOT NULL,
    data json NOT NULL
);


--
-- Name: native_approval_policies; Type: TABLE; Schema: native_approval_live_20261018034134; Owner: -
--

CREATE TABLE native_approval_live_20261018034134.native_approval_policies (
    id character varying(36) NOT NULL,
    policy_key character varying(128) NOT NULL,
    version integer NOT NULL,
    status character varying(16) NOT NULL,
    data json NOT NULL
);


--
-- Name: native_approval_source_archive; Type: TABLE; Schema: native_approval_live_20261018034134; Owner: -
--

CREATE TABLE native_approval_live_20261018034134.native_approval_source_archive (
    table_name character varying NOT NULL,
    ciphertext text NOT NULL,
    sha256 character varying NOT NULL
);


--
-- Name: native_approval_audit native_approval_audit_pkey; Type: CONSTRAINT; Schema: native_approval_live_20261018034134; Owner: -
--

ALTER TABLE ONLY native_approval_live_20261018034134.native_approval_audit
    ADD CONSTRAINT native_approval_audit_pkey PRIMARY KEY (id);


--
-- Name: native_approval_objects native_approval_objects_pkey; Type: CONSTRAINT; Schema: native_approval_live_20261018034134; Owner: -
--

ALTER TABLE ONLY native_approval_live_20261018034134.native_approval_objects
    ADD CONSTRAINT native_approval_objects_pkey PRIMARY KEY (id);


--
-- Name: native_approval_policies native_approval_policies_pkey; Type: CONSTRAINT; Schema: native_approval_live_20261018034134; Owner: -
--

ALTER TABLE ONLY native_approval_live_20261018034134.native_approval_policies
    ADD CONSTRAINT native_approval_policies_pkey PRIMARY KEY (id);


--
-- Name: native_approval_policies native_approval_policies_policy_key_version_key; Type: CONSTRAINT; Schema: native_approval_live_20261018034134; Owner: -
--

ALTER TABLE ONLY native_approval_live_20261018034134.native_approval_policies
    ADD CONSTRAINT native_approval_policies_policy_key_version_key UNIQUE (policy_key, version);


--
-- Name: native_approval_source_archive native_approval_source_archive_pkey; Type: CONSTRAINT; Schema: native_approval_live_20261018034134; Owner: -
--

ALTER TABLE ONLY native_approval_live_20261018034134.native_approval_source_archive
    ADD CONSTRAINT native_approval_source_archive_pkey PRIMARY KEY (table_name);


--
-- Name: native_approval_assignee; Type: INDEX; Schema: native_approval_live_20261018034134; Owner: -
--

CREATE INDEX native_approval_assignee ON native_approval_live_20261018034134.native_approval_objects USING btree (kind, actor, status);


--
-- Name: native_approval_one_active; Type: INDEX; Schema: native_approval_live_20261018034134; Owner: -
--

CREATE UNIQUE INDEX native_approval_one_active ON native_approval_live_20261018034134.native_approval_policies USING btree (policy_key) WHERE ((status)::text = 'active'::text);


--
-- Name: native_approval_order; Type: INDEX; Schema: native_approval_live_20261018034134; Owner: -
--

CREATE INDEX native_approval_order ON native_approval_live_20261018034134.native_approval_objects USING btree (kind, at);


--
-- Name: native_approval_parent; Type: INDEX; Schema: native_approval_live_20261018034134; Owner: -
--

CREATE INDEX native_approval_parent ON native_approval_live_20261018034134.native_approval_objects USING btree (kind, parent);


--
-- PostgreSQL database dump complete
--


