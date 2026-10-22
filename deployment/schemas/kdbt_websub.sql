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
-- Name: websub_deliveries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.websub_deliveries (
    id character varying NOT NULL,
    message_id character varying NOT NULL,
    subscription_id character varying NOT NULL,
    status character varying NOT NULL,
    attempts integer NOT NULL,
    due timestamp with time zone NOT NULL,
    error character varying
);


--
-- Name: websub_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.websub_messages (
    id character varying NOT NULL,
    topic text NOT NULL,
    body bytea NOT NULL,
    content_type character varying NOT NULL,
    digest character varying NOT NULL,
    idempotency_key character varying,
    at timestamp with time zone NOT NULL
);


--
-- Name: websub_subscriptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.websub_subscriptions (
    id character varying NOT NULL,
    topic text NOT NULL,
    callback text NOT NULL,
    active boolean NOT NULL,
    revision integer NOT NULL,
    lease_until timestamp with time zone,
    secret text
);


--
-- Name: websub_topics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.websub_topics (
    name text NOT NULL,
    active boolean NOT NULL
);


--
-- Name: websub_verifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.websub_verifications (
    id character varying NOT NULL,
    subscription_id character varying NOT NULL,
    revision integer NOT NULL,
    mode character varying NOT NULL,
    challenge character varying NOT NULL,
    lease_seconds integer NOT NULL,
    secret text,
    status character varying NOT NULL,
    attempts integer NOT NULL,
    due timestamp with time zone NOT NULL,
    error character varying
);


--
-- Name: websub_deliveries websub_deliveries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.websub_deliveries
    ADD CONSTRAINT websub_deliveries_pkey PRIMARY KEY (id);


--
-- Name: websub_messages websub_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.websub_messages
    ADD CONSTRAINT websub_messages_pkey PRIMARY KEY (id);


--
-- Name: websub_subscriptions websub_subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.websub_subscriptions
    ADD CONSTRAINT websub_subscriptions_pkey PRIMARY KEY (id);


--
-- Name: websub_topics websub_topics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.websub_topics
    ADD CONSTRAINT websub_topics_pkey PRIMARY KEY (name);


--
-- Name: websub_verifications websub_verifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.websub_verifications
    ADD CONSTRAINT websub_verifications_pkey PRIMARY KEY (id);


--
-- Name: ix_websub_deliveries_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_websub_deliveries_pending ON public.websub_deliveries USING btree (status, due);


--
-- Name: ix_websub_verifications_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_websub_verifications_pending ON public.websub_verifications USING btree (status, due);


--
-- Name: ux_websub_message_replay; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_websub_message_replay ON public.websub_messages USING btree (topic, idempotency_key) WHERE (idempotency_key IS NOT NULL);


--
-- PostgreSQL database dump complete
--


