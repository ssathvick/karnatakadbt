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
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: tokenendpointauthmethod; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.tokenendpointauthmethod AS ENUM (
    'private_key_jwt',
    'private_key_jwt_keymanager',
    'client_secret_basic',
    'client_secret_post'
);


SET default_table_access_method = heap;

--
-- Name: dbt_attribute_values; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_attribute_values (
    value_id character varying NOT NULL,
    attribute_id character varying NOT NULL,
    value_code character varying,
    value_display character varying,
    parent_value_id character varying,
    sort_order integer
);


--
-- Name: dbt_attributes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_attributes (
    attribute_id character varying NOT NULL,
    attribute_code character varying,
    attribute_display character varying,
    is_hierarchical boolean
);


--
-- Name: dbt_geo_level_values; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_geo_level_values (
    level_value_id character varying NOT NULL,
    level_id character varying NOT NULL,
    level_value_mnemonic character varying NOT NULL,
    parent_level_value_id character varying
);


--
-- Name: dbt_geo_levels; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_geo_levels (
    level_id character varying NOT NULL,
    level_mnemonic character varying NOT NULL,
    parent_level_id character varying
);


--
-- Name: dbt_sample_households; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_sample_households (
    household_id character varying NOT NULL,
    head_individual_id character varying,
    headship_type character varying,
    size_total integer,
    dwelling_type character varying,
    tenure_status character varying,
    water_source_type character varying,
    sanitation_type character varying,
    lighting_source character varying,
    cooking_fuel_type character varying,
    geo_pcode character varying,
    address_parts jsonb,
    latitude double precision,
    longitude double precision,
    country character varying,
    version character varying
);


--
-- Name: dbt_sample_individuals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_sample_individuals (
    individual_id character varying NOT NULL,
    household_id character varying,
    given_name character varying,
    fathers_name character varying,
    full_name character varying,
    gender character varying,
    relationship_to_head character varying,
    marital_status character varying,
    education_level character varying,
    employment_status character varying,
    disability_status character varying,
    birth_date date,
    birth_year integer,
    age integer,
    phone character varying,
    national_id character varying,
    geo_pcode character varying,
    address_parts jsonb,
    latitude double precision,
    longitude double precision,
    country character varying,
    version character varying
);


--
-- Name: dbt_attribute_values dbt_attribute_values_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_attribute_values
    ADD CONSTRAINT dbt_attribute_values_pkey PRIMARY KEY (value_id, attribute_id);


--
-- Name: dbt_attributes dbt_attributes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_attributes
    ADD CONSTRAINT dbt_attributes_pkey PRIMARY KEY (attribute_id);


--
-- Name: dbt_geo_level_values dbt_geo_level_values_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_geo_level_values
    ADD CONSTRAINT dbt_geo_level_values_pkey PRIMARY KEY (level_value_id);


--
-- Name: dbt_geo_levels dbt_geo_levels_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_geo_levels
    ADD CONSTRAINT dbt_geo_levels_pkey PRIMARY KEY (level_id);


--
-- Name: dbt_sample_households dbt_sample_households_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_sample_households
    ADD CONSTRAINT dbt_sample_households_pkey PRIMARY KEY (household_id);


--
-- Name: dbt_sample_individuals dbt_sample_individuals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_sample_individuals
    ADD CONSTRAINT dbt_sample_individuals_pkey PRIMARY KEY (individual_id);


--
-- Name: dbt_geo_levels uq_level_mnemonic_parent; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_geo_levels
    ADD CONSTRAINT uq_level_mnemonic_parent UNIQUE (level_mnemonic, parent_level_id);


--
-- Name: dbt_geo_level_values uq_value_mnemonic_parent_level; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_geo_level_values
    ADD CONSTRAINT uq_value_mnemonic_parent_level UNIQUE (level_value_mnemonic, parent_level_value_id, level_id);


--
-- Name: ix_dbt_attribute_values_attribute_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_attribute_values_attribute_id ON public.dbt_attribute_values USING btree (attribute_id);


--
-- Name: ix_dbt_attribute_values_parent_value_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_attribute_values_parent_value_id ON public.dbt_attribute_values USING btree (parent_value_id);


--
-- Name: ix_dbt_attributes_attribute_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_attributes_attribute_code ON public.dbt_attributes USING btree (attribute_code);


--
-- Name: ix_dbt_geo_level_values_level_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_geo_level_values_level_id ON public.dbt_geo_level_values USING btree (level_id);


--
-- Name: ix_dbt_geo_level_values_level_value_mnemonic; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_geo_level_values_level_value_mnemonic ON public.dbt_geo_level_values USING btree (level_value_mnemonic);


--
-- Name: ix_dbt_geo_level_values_parent_level_value_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_geo_level_values_parent_level_value_id ON public.dbt_geo_level_values USING btree (parent_level_value_id);


--
-- Name: ix_dbt_geo_levels_level_mnemonic; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_geo_levels_level_mnemonic ON public.dbt_geo_levels USING btree (level_mnemonic);


--
-- Name: ix_dbt_geo_levels_parent_level_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_geo_levels_parent_level_id ON public.dbt_geo_levels USING btree (parent_level_id);


--
-- Name: ix_dbt_sample_households_country; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_sample_households_country ON public.dbt_sample_households USING btree (country);


--
-- Name: ix_dbt_sample_households_geo_pcode; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_sample_households_geo_pcode ON public.dbt_sample_households USING btree (geo_pcode);


--
-- Name: ix_dbt_sample_households_head_individual_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_sample_households_head_individual_id ON public.dbt_sample_households USING btree (head_individual_id);


--
-- Name: ix_dbt_sample_individuals_country; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_sample_individuals_country ON public.dbt_sample_individuals USING btree (country);


--
-- Name: ix_dbt_sample_individuals_geo_pcode; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_sample_individuals_geo_pcode ON public.dbt_sample_individuals USING btree (geo_pcode);


--
-- Name: ix_dbt_sample_individuals_household_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_sample_individuals_household_id ON public.dbt_sample_individuals USING btree (household_id);


--
-- PostgreSQL database dump complete
--

