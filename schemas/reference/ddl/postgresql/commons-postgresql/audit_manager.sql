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
);


--
-- Name: audit_events_2026_11; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_events_2026_11 (
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
);


--
-- Name: audit_events_2026_12; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_events_2026_12 (
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
-- Name: idx_audit_events_actor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_events_actor ON ONLY public.audit_events USING btree (actor_id, occurred_at DESC);


--
-- Name: audit_events_2026_10_actor_id_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_10_actor_id_occurred_at_idx ON public.audit_events_2026_10 USING btree (actor_id, occurred_at DESC);


--
-- Name: idx_audit_events_occurred_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_events_occurred_at ON ONLY public.audit_events USING btree (occurred_at DESC);


--
-- Name: audit_events_2026_10_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_10_occurred_at_idx ON public.audit_events_2026_10 USING btree (occurred_at DESC);


--
-- Name: idx_audit_events_resource; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_events_resource ON ONLY public.audit_events USING btree (resource_type, resource_id, occurred_at DESC);


--
-- Name: audit_events_2026_10_resource_type_resource_id_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_10_resource_type_resource_id_occurred_at_idx ON public.audit_events_2026_10 USING btree (resource_type, resource_id, occurred_at DESC);


--
-- Name: idx_audit_events_trace; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_events_trace ON ONLY public.audit_events USING btree (trace_id) WHERE (trace_id IS NOT NULL);


--
-- Name: audit_events_2026_10_trace_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_10_trace_id_idx ON public.audit_events_2026_10 USING btree (trace_id) WHERE (trace_id IS NOT NULL);


--
-- Name: idx_audit_events_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_events_type ON ONLY public.audit_events USING btree (type, occurred_at DESC);


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

CREATE INDEX audit_events_2026_11_trace_id_idx ON public.audit_events_2026_11 USING btree (trace_id) WHERE (trace_id IS NOT NULL);


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

CREATE INDEX audit_events_2026_12_trace_id_idx ON public.audit_events_2026_12 USING btree (trace_id) WHERE (trace_id IS NOT NULL);


--
-- Name: audit_events_2026_12_type_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_2026_12_type_occurred_at_idx ON public.audit_events_2026_12 USING btree (type, occurred_at DESC);


--
-- Name: audit_events_2026_10_actor_id_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_audit_events_actor ATTACH PARTITION public.audit_events_2026_10_actor_id_occurred_at_idx;


--
-- Name: audit_events_2026_10_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_audit_events_occurred_at ATTACH PARTITION public.audit_events_2026_10_occurred_at_idx;


--
-- Name: audit_events_2026_10_pkey; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.audit_events_pkey ATTACH PARTITION public.audit_events_2026_10_pkey;


--
-- Name: audit_events_2026_10_resource_type_resource_id_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_audit_events_resource ATTACH PARTITION public.audit_events_2026_10_resource_type_resource_id_occurred_at_idx;


--
-- Name: audit_events_2026_10_trace_id_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_audit_events_trace ATTACH PARTITION public.audit_events_2026_10_trace_id_idx;


--
-- Name: audit_events_2026_10_type_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_audit_events_type ATTACH PARTITION public.audit_events_2026_10_type_occurred_at_idx;


--
-- Name: audit_events_2026_11_actor_id_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_audit_events_actor ATTACH PARTITION public.audit_events_2026_11_actor_id_occurred_at_idx;


--
-- Name: audit_events_2026_11_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_audit_events_occurred_at ATTACH PARTITION public.audit_events_2026_11_occurred_at_idx;


--
-- Name: audit_events_2026_11_pkey; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.audit_events_pkey ATTACH PARTITION public.audit_events_2026_11_pkey;


--
-- Name: audit_events_2026_11_resource_type_resource_id_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_audit_events_resource ATTACH PARTITION public.audit_events_2026_11_resource_type_resource_id_occurred_at_idx;


--
-- Name: audit_events_2026_11_trace_id_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_audit_events_trace ATTACH PARTITION public.audit_events_2026_11_trace_id_idx;


--
-- Name: audit_events_2026_11_type_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_audit_events_type ATTACH PARTITION public.audit_events_2026_11_type_occurred_at_idx;


--
-- Name: audit_events_2026_12_actor_id_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_audit_events_actor ATTACH PARTITION public.audit_events_2026_12_actor_id_occurred_at_idx;


--
-- Name: audit_events_2026_12_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_audit_events_occurred_at ATTACH PARTITION public.audit_events_2026_12_occurred_at_idx;


--
-- Name: audit_events_2026_12_pkey; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.audit_events_pkey ATTACH PARTITION public.audit_events_2026_12_pkey;


--
-- Name: audit_events_2026_12_resource_type_resource_id_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_audit_events_resource ATTACH PARTITION public.audit_events_2026_12_resource_type_resource_id_occurred_at_idx;


--
-- Name: audit_events_2026_12_trace_id_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_audit_events_trace ATTACH PARTITION public.audit_events_2026_12_trace_id_idx;


--
-- Name: audit_events_2026_12_type_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.idx_audit_events_type ATTACH PARTITION public.audit_events_2026_12_type_occurred_at_idx;


--
-- PostgreSQL database dump complete
--

