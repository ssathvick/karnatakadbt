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
-- Name: benefittype; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.benefittype AS ENUM (
    'COMMODITY',
    'SERVICE',
    'CASH_DIGITAL',
    'CASH_PHYSICAL',
    'COMBINATION'
);


SET default_table_access_method = heap;

--
-- Name: beneficiary_list_details; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.beneficiary_list_details (
    id character varying NOT NULL,
    beneficiary_list_id character varying NOT NULL,
    registrant_details json NOT NULL,
    number_of_registrants integer NOT NULL,
    entitlement_process_status character varying NOT NULL,
    entitlement_number_of_attempts integer,
    entitlement_processed_date timestamp without time zone,
    entitlement_latest_error_code character varying
);


--
-- Name: beneficiary_list_summary_farmer; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.beneficiary_list_summary_farmer (
    land_holding_q1 double precision,
    land_holding_q2 double precision,
    land_holding_q3 double precision,
    land_holding_mean double precision,
    land_holding_units character varying NOT NULL,
    annual_income_q1 double precision,
    annual_income_q2 double precision,
    annual_income_q3 double precision,
    annual_income_mean double precision,
    annual_income_units character varying NOT NULL,
    average_entitlement_female json,
    average_entitlement_male json,
    entitlement_amount_male_q1 json,
    entitlement_amount_male_q2 json,
    entitlement_amount_male_q3 json,
    entitlement_amount_female_q1 json,
    entitlement_amount_female_q2 json,
    entitlement_amount_female_q3 json,
    entitlement_units json,
    id character varying NOT NULL,
    program_id integer NOT NULL,
    program_mnemonic character varying NOT NULL,
    target_registry character varying NOT NULL,
    beneficiary_list_id character varying NOT NULL,
    number_of_registrants integer NOT NULL,
    number_of_entitlements_processed integer NOT NULL,
    total_disbursement_quantity json,
    average_entitlement_per_person json,
    entitlement_amount_q1 json,
    entitlement_amount_q2 json,
    entitlement_amount_q3 json,
    date_created timestamp without time zone NOT NULL
);


--
-- Name: beneficiary_list_summary_household; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.beneficiary_list_summary_household (
    household_size_q1 double precision,
    household_size_q2 double precision,
    household_size_q3 double precision,
    household_size_mean double precision,
    household_size_units character varying NOT NULL,
    annual_income_q1 double precision,
    annual_income_q2 double precision,
    annual_income_q3 double precision,
    annual_income_mean double precision,
    annual_income_units character varying NOT NULL,
    average_entitlement_female json,
    average_entitlement_male json,
    entitlement_amount_male_q1 json,
    entitlement_amount_male_q2 json,
    entitlement_amount_male_q3 json,
    entitlement_amount_female_q1 json,
    entitlement_amount_female_q2 json,
    entitlement_amount_female_q3 json,
    entitlement_units json,
    id character varying NOT NULL,
    program_id integer NOT NULL,
    program_mnemonic character varying NOT NULL,
    target_registry character varying NOT NULL,
    beneficiary_list_id character varying NOT NULL,
    number_of_registrants integer NOT NULL,
    number_of_entitlements_processed integer NOT NULL,
    total_disbursement_quantity json,
    average_entitlement_per_person json,
    entitlement_amount_q1 json,
    entitlement_amount_q2 json,
    entitlement_amount_q3 json,
    date_created timestamp without time zone NOT NULL
);


--
-- Name: beneficiary_list_summary_student; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.beneficiary_list_summary_student (
    age_mean double precision,
    age_q1 double precision,
    age_q2 double precision,
    age_q3 double precision,
    age_units character varying NOT NULL,
    average_entitlement_female json,
    average_entitlement_male json,
    entitlement_amount_male_q1 json,
    entitlement_amount_male_q2 json,
    entitlement_amount_male_q3 json,
    entitlement_amount_female_q1 json,
    entitlement_amount_female_q2 json,
    entitlement_amount_female_q3 json,
    entitlement_units json,
    id character varying NOT NULL,
    program_id integer NOT NULL,
    program_mnemonic character varying NOT NULL,
    target_registry character varying NOT NULL,
    beneficiary_list_id character varying NOT NULL,
    number_of_registrants integer NOT NULL,
    number_of_entitlements_processed integer NOT NULL,
    total_disbursement_quantity json,
    average_entitlement_per_person json,
    entitlement_amount_q1 json,
    entitlement_amount_q2 json,
    entitlement_amount_q3 json,
    date_created timestamp without time zone NOT NULL
);


--
-- Name: disbursement_batch; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.disbursement_batch (
    id character varying NOT NULL,
    beneficiary_list_id character varying NOT NULL,
    disbursement_cycle_id character varying NOT NULL,
    beneficiary_list_details_id character varying NOT NULL,
    disbursement_envelope_id character varying NOT NULL,
    disbursements json NOT NULL,
    benefit_code_id integer NOT NULL,
    measurement_unit character varying NOT NULL,
    number_of_beneficiaries integer NOT NULL,
    number_of_disbursements integer NOT NULL,
    total_disbursement_quantity double precision NOT NULL,
    disbursement_status character varying NOT NULL,
    disbursement_number_of_attempts integer,
    disbursement_latest_error_code character varying,
    disbursement_processed_date timestamp without time zone
);


--
-- Name: disbursement_envelope; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.disbursement_envelope (
    id character varying NOT NULL,
    beneficiary_list_id character varying NOT NULL,
    benefit_code_id integer NOT NULL,
    benefit_type public.benefittype NOT NULL,
    benefit_program_id integer NOT NULL,
    benefit_program_mnemonic character varying NOT NULL,
    disbursement_cycle_id integer NOT NULL,
    cycle_code_mnemonic character varying NOT NULL,
    number_of_beneficiaries integer NOT NULL,
    number_of_disbursements integer NOT NULL,
    total_disbursement_quantity double precision NOT NULL,
    measurement_unit character varying NOT NULL,
    disbursement_schedule_date timestamp without time zone NOT NULL
);


--
-- Name: beneficiary_list_details beneficiary_list_details_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beneficiary_list_details
    ADD CONSTRAINT beneficiary_list_details_pkey PRIMARY KEY (id);


--
-- Name: beneficiary_list_summary_farmer beneficiary_list_summary_farmer_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beneficiary_list_summary_farmer
    ADD CONSTRAINT beneficiary_list_summary_farmer_pkey PRIMARY KEY (id);


--
-- Name: beneficiary_list_summary_household beneficiary_list_summary_household_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beneficiary_list_summary_household
    ADD CONSTRAINT beneficiary_list_summary_household_pkey PRIMARY KEY (id);


--
-- Name: beneficiary_list_summary_student beneficiary_list_summary_student_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beneficiary_list_summary_student
    ADD CONSTRAINT beneficiary_list_summary_student_pkey PRIMARY KEY (id);


--
-- Name: disbursement_batch disbursement_batch_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disbursement_batch
    ADD CONSTRAINT disbursement_batch_pkey PRIMARY KEY (id);


--
-- Name: disbursement_envelope disbursement_envelope_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disbursement_envelope
    ADD CONSTRAINT disbursement_envelope_pkey PRIMARY KEY (id);


--
-- Name: disbursement_envelope uq_beneficiary_list_id_benefit_code_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disbursement_envelope
    ADD CONSTRAINT uq_beneficiary_list_id_benefit_code_id UNIQUE (beneficiary_list_id, benefit_code_id);


--
-- Name: beneficiary_list_summary_household_beneficiary_list_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX beneficiary_list_summary_household_beneficiary_list_id_idx ON public.beneficiary_list_summary_household USING btree (beneficiary_list_id);


--
-- Name: ix_beneficiary_list_details_beneficiary_list_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_beneficiary_list_details_beneficiary_list_id ON public.beneficiary_list_details USING btree (beneficiary_list_id);


--
-- Name: ix_beneficiary_list_summary_farmer_beneficiary_list_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_beneficiary_list_summary_farmer_beneficiary_list_id ON public.beneficiary_list_summary_farmer USING btree (beneficiary_list_id);


--
-- Name: ix_beneficiary_list_summary_student_beneficiary_list_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_beneficiary_list_summary_student_beneficiary_list_id ON public.beneficiary_list_summary_student USING btree (beneficiary_list_id);


--
-- Name: ix_disbursement_envelope_beneficiary_list_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_envelope_beneficiary_list_id ON public.disbursement_envelope USING btree (beneficiary_list_id);


--
-- Name: ix_disbursement_envelope_benefit_code_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_envelope_benefit_code_id ON public.disbursement_envelope USING btree (benefit_code_id);


--
-- Name: ix_disbursement_envelope_benefit_program_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_envelope_benefit_program_id ON public.disbursement_envelope USING btree (benefit_program_id);


--
-- PostgreSQL database dump complete
--

