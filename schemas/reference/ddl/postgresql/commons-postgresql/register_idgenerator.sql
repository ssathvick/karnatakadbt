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
-- Name: id_pool_farmer; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.id_pool_farmer (
    id_value character varying(32) NOT NULL,
    status character varying(16) DEFAULT 'AVAILABLE'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    issued_at timestamp with time zone
);


--
-- Name: id_pool_household; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.id_pool_household (
    id_value character varying(32) NOT NULL,
    status character varying(16) DEFAULT 'AVAILABLE'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    issued_at timestamp with time zone
);


--
-- Name: id_pool_individual; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.id_pool_individual (
    id_value character varying(32) NOT NULL,
    status character varying(16) DEFAULT 'AVAILABLE'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    issued_at timestamp with time zone
);


--
-- Name: id_pool_farmer id_pool_farmer_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.id_pool_farmer
    ADD CONSTRAINT id_pool_farmer_pkey PRIMARY KEY (id_value);


--
-- Name: id_pool_household id_pool_household_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.id_pool_household
    ADD CONSTRAINT id_pool_household_pkey PRIMARY KEY (id_value);


--
-- Name: id_pool_individual id_pool_individual_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.id_pool_individual
    ADD CONSTRAINT id_pool_individual_pkey PRIMARY KEY (id_value);


--
-- Name: idx_farmer_available; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_farmer_available ON public.id_pool_farmer USING btree (status) WHERE ((status)::text = 'AVAILABLE'::text);


--
-- Name: idx_household_available; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_available ON public.id_pool_household USING btree (status) WHERE ((status)::text = 'AVAILABLE'::text);


--
-- Name: idx_individual_available; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_individual_available ON public.id_pool_individual USING btree (status) WHERE ((status)::text = 'AVAILABLE'::text);


--
-- PostgreSQL database dump complete
--

