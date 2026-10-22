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

--
-- Name: audit_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_events (
    id text NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    ingested_at timestamp with time zone DEFAULT now() NOT NULL,
    source text NOT NULL,
    type text NOT NULL,
    subject text,
    actor_type text NOT NULL,
    actor_id text NOT NULL,
    resource_type text,
    resource_id text,
    action text NOT NULL,
    outcome text NOT NULL,
    reason text,
    trace_id text,
    details jsonb
)
PARTITION BY RANGE (occurred_at);


SET default_table_access_method = heap;

--
-- Name: audit_events_2026_10; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_events_2026_10 (
    id text CONSTRAINT audit_events_id_not_null NOT NULL,
    occurred_at timestamp with time zone CONSTRAINT audit_events_occurred_at_not_null NOT NULL,
    ingested_at timestamp with time zone DEFAULT now() CONSTRAINT audit_events_ingested_at_not_null NOT NULL,
    source text CONSTRAINT audit_events_source_not_null NOT NULL,
    type text CONSTRAINT audit_events_type_not_null NOT NULL,
    subject text,
    actor_type text CONSTRAINT audit_events_actor_type_not_null NOT NULL,
    actor_id text CONSTRAINT audit_events_actor_id_not_null NOT NULL,
    resource_type text,
    resource_id text,
    action text CONSTRAINT audit_events_action_not_null NOT NULL,
    outcome text CONSTRAINT audit_events_outcome_not_null NOT NULL,
    reason text,
    trace_id text,
    details jsonb
);


--
-- Name: audit_events_2026_11; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_events_2026_11 (
    id text CONSTRAINT audit_events_id_not_null NOT NULL,
    occurred_at timestamp with time zone CONSTRAINT audit_events_occurred_at_not_null NOT NULL,
    ingested_at timestamp with time zone DEFAULT now() CONSTRAINT audit_events_ingested_at_not_null NOT NULL,
    source text CONSTRAINT audit_events_source_not_null NOT NULL,
    type text CONSTRAINT audit_events_type_not_null NOT NULL,
    subject text,
    actor_type text CONSTRAINT audit_events_actor_type_not_null NOT NULL,
    actor_id text CONSTRAINT audit_events_actor_id_not_null NOT NULL,
    resource_type text,
    resource_id text,
    action text CONSTRAINT audit_events_action_not_null NOT NULL,
    outcome text CONSTRAINT audit_events_outcome_not_null NOT NULL,
    reason text,
    trace_id text,
    details jsonb
);


--
-- Name: audit_events_2026_12; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_events_2026_12 (
    id text CONSTRAINT audit_events_id_not_null NOT NULL,
    occurred_at timestamp with time zone CONSTRAINT audit_events_occurred_at_not_null NOT NULL,
    ingested_at timestamp with time zone DEFAULT now() CONSTRAINT audit_events_ingested_at_not_null NOT NULL,
    source text CONSTRAINT audit_events_source_not_null NOT NULL,
    type text CONSTRAINT audit_events_type_not_null NOT NULL,
    subject text,
    actor_type text CONSTRAINT audit_events_actor_type_not_null NOT NULL,
    actor_id text CONSTRAINT audit_events_actor_id_not_null NOT NULL,
    resource_type text,
    resource_id text,
    action text CONSTRAINT audit_events_action_not_null NOT NULL,
    outcome text CONSTRAINT audit_events_outcome_not_null NOT NULL,
    reason text,
    trace_id text,
    details jsonb
);


--
-- Name: native_audit_outbox; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.native_audit_outbox (
    id text NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    event jsonb NOT NULL,
    accepted_at timestamp with time zone DEFAULT now() NOT NULL,
    published_at timestamp with time zone,
    sequence bigint NOT NULL
);


--
-- Name: native_audit_outbox_sequence_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.native_audit_outbox ALTER COLUMN sequence ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.native_audit_outbox_sequence_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: audit_events_2026_10; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_events ATTACH PARTITION public.audit_events_2026_10 FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00');


--
-- Name: audit_events_2026_11; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_events ATTACH PARTITION public.audit_events_2026_11 FOR VALUES FROM ('2026-11-01 00:00:00+00') TO ('2026-12-01 00:00:00+00');


--
-- Name: audit_events_2026_12; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_events ATTACH PARTITION public.audit_events_2026_12 FOR VALUES FROM ('2026-12-01 00:00:00+00') TO ('2027-01-01 00:00:00+00');


--
-- Name: audit_events audit_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_events
    ADD CONSTRAINT audit_events_pkey PRIMARY KEY (id, occurred_at);


--
-- Name: audit_events_2026_10 audit_events_2026_10_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_events_2026_10
    ADD CONSTRAINT audit_events_2026_10_pkey PRIMARY KEY (id, occurred_at);


--
-- Name: audit_events_2026_11 audit_events_2026_11_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_events_2026_11
    ADD CONSTRAINT audit_events_2026_11_pkey PRIMARY KEY (id, occurred_at);


--
-- Name: audit_events_2026_12 audit_events_2026_12_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_events_2026_12
    ADD CONSTRAINT audit_events_2026_12_pkey PRIMARY KEY (id, occurred_at);


--
-- Name: native_audit_outbox native_audit_outbox_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.native_audit_outbox
    ADD CONSTRAINT native_audit_outbox_pkey PRIMARY KEY (id, occurred_at);


--
-- Name: native_audit_actor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX native_audit_actor ON ONLY public.audit_events USING btree (actor_id, occurred_at DESC);


--
-- Name: audit_events_2026_10_actor_id_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_10_actor_id_occurred_at_idx ON public.audit_events_2026_10 USING btree (actor_id, occurred_at DESC);


--
-- Name: native_audit_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX native_audit_time ON ONLY public.audit_events USING btree (occurred_at DESC);


--
-- Name: audit_events_2026_10_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_10_occurred_at_idx ON public.audit_events_2026_10 USING btree (occurred_at DESC);


--
-- Name: native_audit_resource; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX native_audit_resource ON ONLY public.audit_events USING btree (resource_type, resource_id, occurred_at DESC);


--
-- Name: audit_events_2026_10_resource_type_resource_id_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_10_resource_type_resource_id_occurred_at_idx ON public.audit_events_2026_10 USING btree (resource_type, resource_id, occurred_at DESC);


--
-- Name: native_audit_trace; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX native_audit_trace ON ONLY public.audit_events USING btree (trace_id);


--
-- Name: audit_events_2026_10_trace_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_10_trace_id_idx ON public.audit_events_2026_10 USING btree (trace_id);


--
-- Name: native_audit_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX native_audit_type ON ONLY public.audit_events USING btree (type, occurred_at DESC);


--
-- Name: audit_events_2026_10_type_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_10_type_occurred_at_idx ON public.audit_events_2026_10 USING btree (type, occurred_at DESC);


--
-- Name: audit_events_2026_11_actor_id_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_11_actor_id_occurred_at_idx ON public.audit_events_2026_11 USING btree (actor_id, occurred_at DESC);


--
-- Name: audit_events_2026_11_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_11_occurred_at_idx ON public.audit_events_2026_11 USING btree (occurred_at DESC);


--
-- Name: audit_events_2026_11_resource_type_resource_id_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_11_resource_type_resource_id_occurred_at_idx ON public.audit_events_2026_11 USING btree (resource_type, resource_id, occurred_at DESC);


--
-- Name: audit_events_2026_11_trace_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_11_trace_id_idx ON public.audit_events_2026_11 USING btree (trace_id);


--
-- Name: audit_events_2026_11_type_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_11_type_occurred_at_idx ON public.audit_events_2026_11 USING btree (type, occurred_at DESC);


--
-- Name: audit_events_2026_12_actor_id_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_12_actor_id_occurred_at_idx ON public.audit_events_2026_12 USING btree (actor_id, occurred_at DESC);


--
-- Name: audit_events_2026_12_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_12_occurred_at_idx ON public.audit_events_2026_12 USING btree (occurred_at DESC);


--
-- Name: audit_events_2026_12_resource_type_resource_id_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_12_resource_type_resource_id_occurred_at_idx ON public.audit_events_2026_12 USING btree (resource_type, resource_id, occurred_at DESC);


--
-- Name: audit_events_2026_12_trace_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_12_trace_id_idx ON public.audit_events_2026_12 USING btree (trace_id);


--
-- Name: audit_events_2026_12_type_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_12_type_occurred_at_idx ON public.audit_events_2026_12 USING btree (type, occurred_at DESC);


--
-- Name: audit_events_2026_10_actor_id_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.native_audit_actor ATTACH PARTITION public.audit_events_2026_10_actor_id_occurred_at_idx;


--
-- Name: audit_events_2026_10_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.native_audit_time ATTACH PARTITION public.audit_events_2026_10_occurred_at_idx;


--
-- Name: audit_events_2026_10_pkey; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.audit_events_pkey ATTACH PARTITION public.audit_events_2026_10_pkey;


--
-- Name: audit_events_2026_10_resource_type_resource_id_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.native_audit_resource ATTACH PARTITION public.audit_events_2026_10_resource_type_resource_id_occurred_at_idx;


--
-- Name: audit_events_2026_10_trace_id_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.native_audit_trace ATTACH PARTITION public.audit_events_2026_10_trace_id_idx;


--
-- Name: audit_events_2026_10_type_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.native_audit_type ATTACH PARTITION public.audit_events_2026_10_type_occurred_at_idx;


--
-- Name: audit_events_2026_11_actor_id_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.native_audit_actor ATTACH PARTITION public.audit_events_2026_11_actor_id_occurred_at_idx;


--
-- Name: audit_events_2026_11_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.native_audit_time ATTACH PARTITION public.audit_events_2026_11_occurred_at_idx;


--
-- Name: audit_events_2026_11_pkey; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.audit_events_pkey ATTACH PARTITION public.audit_events_2026_11_pkey;


--
-- Name: audit_events_2026_11_resource_type_resource_id_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.native_audit_resource ATTACH PARTITION public.audit_events_2026_11_resource_type_resource_id_occurred_at_idx;


--
-- Name: audit_events_2026_11_trace_id_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.native_audit_trace ATTACH PARTITION public.audit_events_2026_11_trace_id_idx;


--
-- Name: audit_events_2026_11_type_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.native_audit_type ATTACH PARTITION public.audit_events_2026_11_type_occurred_at_idx;


--
-- Name: audit_events_2026_12_actor_id_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.native_audit_actor ATTACH PARTITION public.audit_events_2026_12_actor_id_occurred_at_idx;


--
-- Name: audit_events_2026_12_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.native_audit_time ATTACH PARTITION public.audit_events_2026_12_occurred_at_idx;


--
-- Name: audit_events_2026_12_pkey; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.audit_events_pkey ATTACH PARTITION public.audit_events_2026_12_pkey;


--
-- Name: audit_events_2026_12_resource_type_resource_id_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.native_audit_resource ATTACH PARTITION public.audit_events_2026_12_resource_type_resource_id_occurred_at_idx;


--
-- Name: audit_events_2026_12_trace_id_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.native_audit_trace ATTACH PARTITION public.audit_events_2026_12_trace_id_idx;


--
-- Name: audit_events_2026_12_type_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.native_audit_type ATTACH PARTITION public.audit_events_2026_12_type_occurred_at_idx;


--
-- PostgreSQL database dump complete
--


