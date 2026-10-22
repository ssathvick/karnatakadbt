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
-- Name: account_statement_lobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.account_statement_lobs (
    statement_id character varying NOT NULL,
    statement_lob text NOT NULL,
    id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: account_statements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.account_statements (
    statement_id character varying NOT NULL,
    statement_date timestamp without time zone NOT NULL,
    account_number character varying,
    reference_number character varying,
    statement_number character varying,
    sequence_number character varying,
    statement_upload_timestamp timestamp without time zone NOT NULL,
    statement_process_status character varying NOT NULL,
    statement_process_timestamp timestamp without time zone,
    statement_process_error_code character varying,
    statement_process_attempts integer NOT NULL,
    id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: disbursement_batch_control; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.disbursement_batch_control (
    disbursement_cycle_id integer NOT NULL,
    disbursement_envelope_id character varying NOT NULL,
    fa_resolution_status character varying NOT NULL,
    fa_resolution_timestamp timestamp without time zone,
    fa_resolution_latest_error_code character varying,
    fa_resolution_attempts integer NOT NULL,
    sponsor_bank_dispatch_status character varying NOT NULL,
    sponsor_bank_dispatch_timestamp timestamp without time zone,
    sponsor_bank_dispatch_latest_error_code character varying,
    sponsor_bank_dispatch_attempts integer NOT NULL,
    geo_resolution_status character varying NOT NULL,
    geo_resolution_timestamp timestamp without time zone,
    geo_resolution_latest_error_code character varying,
    geo_resolution_attempts integer NOT NULL,
    warehouse_allocation_status character varying NOT NULL,
    warehouse_allocation_timestamp timestamp without time zone,
    warehouse_allocation_latest_error_code character varying,
    warehouse_allocation_attempts integer NOT NULL,
    agency_allocation_status character varying NOT NULL,
    agency_allocation_timestamp timestamp without time zone,
    agency_allocation_latest_error_code character varying,
    agency_allocation_attempts integer NOT NULL,
    id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: disbursement_batch_control_geo; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.disbursement_batch_control_geo (
    disbursement_cycle_id character varying NOT NULL,
    disbursement_envelope_id character varying NOT NULL,
    disbursement_batch_control_id character varying NOT NULL,
    administrative_zone_id_large character varying NOT NULL,
    administrative_zone_mnemonic_large character varying NOT NULL,
    administrative_zone_id_small character varying NOT NULL,
    administrative_zone_mnemonic_small character varying NOT NULL,
    no_of_beneficiaries integer NOT NULL,
    total_quantity double precision NOT NULL,
    warehouse_id character varying,
    warehouse_mnemonic character varying,
    warehouse_additional_attributes character varying,
    agency_id character varying,
    agency_mnemonic character varying,
    agency_additional_attributes character varying,
    warehouse_notification_status character varying NOT NULL,
    warehouse_notification_attempts integer NOT NULL,
    warehouse_notification_latest_error_code character varying,
    agency_notification_status character varying NOT NULL,
    agency_notification_attempts integer NOT NULL,
    agency_notification_latest_error_code character varying,
    id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: disbursement_batch_control_geo_attributes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.disbursement_batch_control_geo_attributes (
    disbursement_batch_control_id character varying NOT NULL,
    warehouse_name character varying,
    warehouse_admin_name character varying,
    warehouse_admin_email character varying,
    warehouse_admin_phone character varying,
    agency_name character varying,
    agency_admin_name character varying,
    agency_admin_email character varying,
    agency_admin_phone character varying,
    id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: disbursement_envelopes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.disbursement_envelopes (
    benefit_program_id integer NOT NULL,
    benefit_program_mnemonic character varying NOT NULL,
    benefit_program_description character varying,
    target_registry character varying,
    benefit_code_id integer NOT NULL,
    benefit_code_mnemonic character varying NOT NULL,
    benefit_code_description character varying,
    benefit_type character varying NOT NULL,
    disbursement_cycle_id integer NOT NULL,
    disbursement_frequency character varying NOT NULL,
    cycle_code_mnemonic character varying NOT NULL,
    number_of_beneficiaries integer NOT NULL,
    number_of_disbursements integer NOT NULL,
    total_disbursement_quantity integer NOT NULL,
    measurement_unit character varying NOT NULL,
    disbursement_schedule_date date NOT NULL,
    receipt_time_stamp timestamp without time zone NOT NULL,
    cancellation_status character varying NOT NULL,
    cancellation_timestamp timestamp without time zone,
    id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: disbursement_error_recons; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.disbursement_error_recons (
    statement_id character varying,
    statement_number character varying,
    statement_sequence character varying,
    entry_sequence character varying,
    entry_date timestamp without time zone,
    value_date timestamp without time zone,
    error_reason character varying,
    reconciliation_id character varying NOT NULL,
    disbursement_batch_control_geo_id character varying,
    bank_reference_number character varying,
    id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: disbursement_recons; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.disbursement_recons (
    disbursement_batch_control_id character varying NOT NULL,
    disbursement_id character varying NOT NULL,
    disbursement_batch_control_geo_id character varying,
    disbursement_envelope_id character varying,
    beneficiary_name_from_bank character varying,
    remittance_reference_number character varying,
    remittance_statement_id character varying,
    remittance_statement_number character varying,
    remittance_statement_sequence character varying,
    remittance_entry_sequence character varying,
    remittance_entry_date timestamp without time zone,
    remittance_value_date timestamp without time zone,
    reversal_found boolean NOT NULL,
    reversal_statement_id character varying,
    reversal_statement_number character varying,
    reversal_statement_sequence character varying,
    reversal_entry_sequence character varying,
    reversal_entry_date timestamp without time zone,
    reversal_value_date timestamp without time zone,
    reversal_reason character varying,
    id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: disbursement_resolution_financial_address; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.disbursement_resolution_financial_address (
    disbursement_batch_control_id character varying,
    disbursement_id character varying NOT NULL,
    beneficiary_id character varying NOT NULL,
    mapper_resolved_fa character varying,
    mapper_resolved_name character varying,
    mapper_resolved_fa_type character varying,
    bank_account_number character varying,
    bank_code character varying,
    branch_code character varying,
    mobile_number character varying,
    mobile_wallet_provider character varying,
    email_address character varying,
    email_wallet_provider character varying,
    id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: disbursement_resolution_geo_address; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.disbursement_resolution_geo_address (
    disbursement_id character varying NOT NULL,
    disbursement_cycle_id character varying NOT NULL,
    disbursement_envelope_id character varying NOT NULL,
    disbursement_batch_control_id character varying NOT NULL,
    disbursement_batch_control_geo_id character varying NOT NULL,
    beneficiary_id character varying NOT NULL,
    administrative_zone_id_large character varying NOT NULL,
    administrative_zone_mnemonic_large character varying NOT NULL,
    administrative_zone_id_small character varying NOT NULL,
    administrative_zone_mnemonic_small character varying NOT NULL,
    warehouse_id character varying,
    warehouse_mnemonic character varying,
    agency_id character varying,
    agency_mnemonic character varying,
    beneficiary_name character varying,
    beneficiary_phone character varying,
    beneficiary_email character varying,
    beneficiary_notification_status character varying NOT NULL,
    beneficiary_notification_attempts integer NOT NULL,
    beneficiary_notification_latest_error_code character varying,
    id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: disbursements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.disbursements (
    disbursement_envelope_id character varying NOT NULL,
    beneficiary_id character varying NOT NULL,
    beneficiary_name character varying,
    disbursement_quantity double precision NOT NULL,
    compute_elements json,
    narrative character varying NOT NULL,
    receipt_time_stamp timestamp without time zone NOT NULL,
    cancellation_status character varying NOT NULL,
    cancellation_time_stamp timestamp without time zone,
    disbursement_cycle_id integer NOT NULL,
    disbursement_batch_control_id character varying NOT NULL,
    id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: envelope_batch_status_for_cash; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.envelope_batch_status_for_cash (
    disbursement_envelope_id character varying NOT NULL,
    funds_available_with_bank character varying NOT NULL,
    funds_available_latest_timestamp timestamp without time zone,
    funds_available_latest_error_code character varying,
    funds_available_attempts integer NOT NULL,
    funds_blocked_with_bank character varying NOT NULL,
    funds_blocked_latest_timestamp timestamp without time zone,
    funds_blocked_latest_error_code character varying,
    funds_blocked_attempts integer NOT NULL,
    funds_blocked_reference_number character varying,
    number_of_disbursements_shipped integer NOT NULL,
    number_of_disbursements_reconciled integer NOT NULL,
    number_of_disbursements_reversed integer NOT NULL,
    id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: envelope_control; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.envelope_control (
    disbursement_envelope_id character varying NOT NULL,
    number_of_disbursements_received integer NOT NULL,
    total_disbursement_quantity_received integer NOT NULL,
    id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: notification_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_logs (
    notification_type character varying NOT NULL,
    recipient character varying NOT NULL,
    payload text NOT NULL,
    response text,
    error_message text,
    sent_at timestamp without time zone NOT NULL,
    processed_at timestamp without time zone,
    id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: account_statement_lobs account_statement_lobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_statement_lobs
    ADD CONSTRAINT account_statement_lobs_pkey PRIMARY KEY (id);


--
-- Name: account_statements account_statements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_statements
    ADD CONSTRAINT account_statements_pkey PRIMARY KEY (id);


--
-- Name: disbursement_batch_control_geo_attributes disbursement_batch_control_geo_attributes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disbursement_batch_control_geo_attributes
    ADD CONSTRAINT disbursement_batch_control_geo_attributes_pkey PRIMARY KEY (id);


--
-- Name: disbursement_batch_control_geo disbursement_batch_control_geo_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disbursement_batch_control_geo
    ADD CONSTRAINT disbursement_batch_control_geo_pkey PRIMARY KEY (id);


--
-- Name: disbursement_batch_control disbursement_batch_control_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disbursement_batch_control
    ADD CONSTRAINT disbursement_batch_control_pkey PRIMARY KEY (id);


--
-- Name: disbursement_envelopes disbursement_envelopes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disbursement_envelopes
    ADD CONSTRAINT disbursement_envelopes_pkey PRIMARY KEY (id);


--
-- Name: disbursement_error_recons disbursement_error_recons_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disbursement_error_recons
    ADD CONSTRAINT disbursement_error_recons_pkey PRIMARY KEY (id);


--
-- Name: disbursement_recons disbursement_recons_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disbursement_recons
    ADD CONSTRAINT disbursement_recons_pkey PRIMARY KEY (id);


--
-- Name: disbursement_recons disbursement_recons_remittance_reference_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disbursement_recons
    ADD CONSTRAINT disbursement_recons_remittance_reference_number_key UNIQUE (remittance_reference_number);


--
-- Name: disbursement_resolution_financial_address disbursement_resolution_financial_address_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disbursement_resolution_financial_address
    ADD CONSTRAINT disbursement_resolution_financial_address_pkey PRIMARY KEY (id);


--
-- Name: disbursement_resolution_geo_address disbursement_resolution_geo_address_disbursement_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disbursement_resolution_geo_address
    ADD CONSTRAINT disbursement_resolution_geo_address_disbursement_id_key UNIQUE (disbursement_id);


--
-- Name: disbursement_resolution_geo_address disbursement_resolution_geo_address_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disbursement_resolution_geo_address
    ADD CONSTRAINT disbursement_resolution_geo_address_pkey PRIMARY KEY (id);


--
-- Name: disbursements disbursements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disbursements
    ADD CONSTRAINT disbursements_pkey PRIMARY KEY (id);


--
-- Name: envelope_batch_status_for_cash envelope_batch_status_for_cash_disbursement_envelope_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.envelope_batch_status_for_cash
    ADD CONSTRAINT envelope_batch_status_for_cash_disbursement_envelope_id_key UNIQUE (disbursement_envelope_id);


--
-- Name: envelope_batch_status_for_cash envelope_batch_status_for_cash_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.envelope_batch_status_for_cash
    ADD CONSTRAINT envelope_batch_status_for_cash_pkey PRIMARY KEY (id);


--
-- Name: envelope_control envelope_control_disbursement_envelope_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.envelope_control
    ADD CONSTRAINT envelope_control_disbursement_envelope_id_key UNIQUE (disbursement_envelope_id);


--
-- Name: envelope_control envelope_control_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.envelope_control
    ADD CONSTRAINT envelope_control_pkey PRIMARY KEY (id);


--
-- Name: notification_logs notification_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_logs
    ADD CONSTRAINT notification_logs_pkey PRIMARY KEY (id);


--
-- Name: ix_account_statement_lobs_statement_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_account_statement_lobs_statement_id ON public.account_statement_lobs USING btree (statement_id);


--
-- Name: ix_account_statements_statement_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_account_statements_statement_id ON public.account_statements USING btree (statement_id);


--
-- Name: ix_disbursement_batch_control_disbursement_cycle_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_batch_control_disbursement_cycle_id ON public.disbursement_batch_control USING btree (disbursement_cycle_id);


--
-- Name: ix_disbursement_batch_control_disbursement_envelope_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_batch_control_disbursement_envelope_id ON public.disbursement_batch_control USING btree (disbursement_envelope_id);


--
-- Name: ix_disbursement_batch_control_geo_attributes_disburseme_c7b0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_batch_control_geo_attributes_disburseme_c7b0 ON public.disbursement_batch_control_geo_attributes USING btree (disbursement_batch_control_id);


--
-- Name: ix_disbursement_batch_control_geo_disbursement_batch_control_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_batch_control_geo_disbursement_batch_control_id ON public.disbursement_batch_control_geo USING btree (disbursement_batch_control_id);


--
-- Name: ix_disbursement_batch_control_geo_disbursement_cycle_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_batch_control_geo_disbursement_cycle_id ON public.disbursement_batch_control_geo USING btree (disbursement_cycle_id);


--
-- Name: ix_disbursement_batch_control_geo_disbursement_envelope_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_batch_control_geo_disbursement_envelope_id ON public.disbursement_batch_control_geo USING btree (disbursement_envelope_id);


--
-- Name: ix_disbursement_error_recons_disbursement_batch_control_geo_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_error_recons_disbursement_batch_control_geo_id ON public.disbursement_error_recons USING btree (disbursement_batch_control_geo_id);


--
-- Name: ix_disbursement_error_recons_reconciliation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_error_recons_reconciliation_id ON public.disbursement_error_recons USING btree (reconciliation_id);


--
-- Name: ix_disbursement_error_recons_statement_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_error_recons_statement_id ON public.disbursement_error_recons USING btree (statement_id);


--
-- Name: ix_disbursement_recons_disbursement_batch_control_geo_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_recons_disbursement_batch_control_geo_id ON public.disbursement_recons USING btree (disbursement_batch_control_geo_id);


--
-- Name: ix_disbursement_recons_disbursement_batch_control_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_recons_disbursement_batch_control_id ON public.disbursement_recons USING btree (disbursement_batch_control_id);


--
-- Name: ix_disbursement_recons_disbursement_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_disbursement_recons_disbursement_id ON public.disbursement_recons USING btree (disbursement_id);


--
-- Name: ix_disbursement_resolution_financial_address_beneficiary_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_resolution_financial_address_beneficiary_id ON public.disbursement_resolution_financial_address USING btree (beneficiary_id);


--
-- Name: ix_disbursement_resolution_financial_address_disburseme_70f6; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_resolution_financial_address_disburseme_70f6 ON public.disbursement_resolution_financial_address USING btree (disbursement_batch_control_id);


--
-- Name: ix_disbursement_resolution_financial_address_disbursement_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_disbursement_resolution_financial_address_disbursement_id ON public.disbursement_resolution_financial_address USING btree (disbursement_id);


--
-- Name: ix_disbursement_resolution_geo_address_agency_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_resolution_geo_address_agency_id ON public.disbursement_resolution_geo_address USING btree (agency_id);


--
-- Name: ix_disbursement_resolution_geo_address_beneficiary_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_resolution_geo_address_beneficiary_id ON public.disbursement_resolution_geo_address USING btree (beneficiary_id);


--
-- Name: ix_disbursement_resolution_geo_address_disbursement_bat_5115; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_resolution_geo_address_disbursement_bat_5115 ON public.disbursement_resolution_geo_address USING btree (disbursement_batch_control_id);


--
-- Name: ix_disbursement_resolution_geo_address_disbursement_bat_6ec4; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_resolution_geo_address_disbursement_bat_6ec4 ON public.disbursement_resolution_geo_address USING btree (disbursement_batch_control_geo_id);


--
-- Name: ix_disbursement_resolution_geo_address_disbursement_cycle_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_resolution_geo_address_disbursement_cycle_id ON public.disbursement_resolution_geo_address USING btree (disbursement_cycle_id);


--
-- Name: ix_disbursement_resolution_geo_address_disbursement_envelope_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_resolution_geo_address_disbursement_envelope_id ON public.disbursement_resolution_geo_address USING btree (disbursement_envelope_id);


--
-- Name: ix_disbursement_resolution_geo_address_warehouse_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursement_resolution_geo_address_warehouse_id ON public.disbursement_resolution_geo_address USING btree (warehouse_id);


--
-- Name: ix_disbursements_disbursement_envelope_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_disbursements_disbursement_envelope_id ON public.disbursements USING btree (disbursement_envelope_id);


--
-- Name: ix_notification_logs_notification_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notification_logs_notification_type ON public.notification_logs USING btree (notification_type);


--
-- Name: ix_notification_logs_recipient; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notification_logs_recipient ON public.notification_logs USING btree (recipient);


--
-- PostgreSQL database dump complete
--

