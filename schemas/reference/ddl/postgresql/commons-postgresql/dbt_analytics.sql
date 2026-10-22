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
-- Name: aggregate_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aggregate_metrics (
    source text,
    metric text,
    label text,
    value double precision,
    refreshed_at timestamp with time zone,
    stale boolean
);


--
-- Name: knowledge_daily_usage; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_daily_usage (
    day date,
    module text,
    article integer,
    version integer,
    event_name text,
    helpful integer,
    events integer,
    zero_results integer
);


--
-- Name: knowledge_governance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_governance (
    module text,
    status text,
    articles integer,
    live integer,
    refreshed_at timestamp with time zone
);


--
-- PostgreSQL database dump complete
--

