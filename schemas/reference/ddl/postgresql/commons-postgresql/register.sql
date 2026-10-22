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
-- Name: registry_theme_attribute_name_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.registry_theme_attribute_name_enum AS ENUM (
    'primary_color_1',
    'primary_color_2',
    'secondary_color_1',
    'secondary_color_2',
    'secondary_color_3',
    'neutral_color_1',
    'neutral_color_2',
    'font_family',
    'font_url',
    'dashboard_image'
);


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
-- Name: awe_req_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.awe_req_events (
    event_id character varying NOT NULL,
    event_type character varying NOT NULL,
    request_id character varying NOT NULL,
    artifact_type character varying NOT NULL,
    artifact_id character varying NOT NULL,
    status character varying NOT NULL,
    stage_order integer,
    actor character varying,
    occurred_at timestamp with time zone NOT NULL,
    received_at timestamp with time zone NOT NULL,
    applied boolean NOT NULL,
    error text
);


--
-- Name: data_models; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_models (
    data_model_id character varying NOT NULL,
    data_model_mnemonic character varying NOT NULL,
    pattern_for_data_model character varying NOT NULL,
    response_template_document_id character varying,
    is_active boolean NOT NULL
);


--
-- Name: dedup_results_intake_forms_vs_intake_forms; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dedup_results_intake_forms_vs_intake_forms (
    dedup_result_id character varying NOT NULL,
    submission_id character varying NOT NULL,
    section_register_id character varying NOT NULL,
    candidate_submission_id character varying NOT NULL,
    match_score double precision NOT NULL,
    field_matches json NOT NULL,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: dedup_results_intake_forms_vs_register; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dedup_results_intake_forms_vs_register (
    dedup_result_id character varying NOT NULL,
    submission_id character varying NOT NULL,
    section_register_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    match_score double precision NOT NULL,
    field_matches json NOT NULL,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: deduplication_change_request_results; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.deduplication_change_request_results (
    dedup_result_id character varying NOT NULL,
    change_request_id character varying NOT NULL,
    candidate_change_request_id character varying NOT NULL,
    match_score double precision NOT NULL,
    field_matches json NOT NULL,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: deduplication_register_results; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.deduplication_register_results (
    dedup_result_id character varying NOT NULL,
    change_request_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    match_score double precision NOT NULL,
    field_matches json NOT NULL,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: dbt_change_request_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_change_request_documents (
    change_request_id character varying NOT NULL,
    document_id character varying NOT NULL,
    section_id character varying NOT NULL,
    label character varying NOT NULL
);


--
-- Name: dbt_completion_score_computation_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_completion_score_computation_queue (
    queue_id character varying NOT NULL,
    register_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    section_id character varying NOT NULL,
    change_request_id character varying,
    submission_id character varying,
    compute_status character varying NOT NULL,
    compute_number_of_attempts integer NOT NULL,
    compute_processed_timestamp timestamp without time zone,
    compute_latest_error_code character varying
);


--
-- Name: dbt_functional_id_generation_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_functional_id_generation_queue (
    queue_id character varying NOT NULL,
    register_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    resolved_id character varying,
    resolved_prefix character varying,
    resolved_suffix character varying,
    id_allocation_status character varying NOT NULL,
    id_allocation_no_of_attempts integer NOT NULL,
    id_allocation_latest_timestamp timestamp without time zone,
    id_allocation_latest_error_code character varying,
    id_updation_status character varying NOT NULL,
    id_updation_no_of_attempts integer NOT NULL,
    id_updation_latest_timestamp timestamp without time zone,
    id_updation_latest_error_code character varying
);


--
-- Name: dbt_input_mechanisms; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_input_mechanisms (
    mechanism_id character varying NOT NULL,
    register_id character varying NOT NULL,
    mechanism_type character varying NOT NULL,
    display_key character varying NOT NULL
);


--
-- Name: dbt_intake_form_definitions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_intake_form_definitions (
    form_id character varying NOT NULL,
    register_id character varying NOT NULL,
    form_mnemonic character varying NOT NULL,
    form_description text,
    number_of_verifications integer NOT NULL,
    used_only_in_ingestion_pipeline boolean NOT NULL
);


--
-- Name: dbt_intake_form_household_assets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_intake_form_household_assets (
    submission_id uuid NOT NULL,
    application_reference character varying,
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    asset_type character varying,
    asset_category character varying,
    quantity integer,
    size_value numeric,
    size_unit character varying,
    size_band character varying,
    details json
);


--
-- Name: dbt_intake_form_household_housing_and_services; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_intake_form_household_housing_and_services (
    submission_id uuid NOT NULL,
    application_reference character varying,
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    dwelling_type character varying,
    roof_material character varying,
    wall_material character varying,
    floor_material character varying,
    tenure_status character varying,
    water_source_type character varying,
    water_distance_minutes integer,
    sanitation_type character varying,
    lighting_source character varying,
    cooking_fuel_type character varying
);


--
-- Name: dbt_intake_form_household_programs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_intake_form_household_programs (
    submission_id uuid NOT NULL,
    application_reference character varying,
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    program_name character varying,
    program_start_date date,
    program_exit_date date
);


--
-- Name: dbt_intake_form_households; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_intake_form_households (
    submission_id uuid NOT NULL,
    application_reference character varying,
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    latitude double precision,
    longitude double precision,
    altitude double precision,
    plus_code character varying,
    address_line_1 character varying,
    address_line_2 character varying,
    postal_code character varying,
    country_code character varying,
    geo_lowest_level_value_id character varying,
    geo_code_hierarchy_json jsonb,
    household_head_internal_record_id character varying,
    household_head_name character varying,
    headship_type character varying,
    husband_dead boolean DEFAULT false,
    husband_dead_date date,
    size_total integer,
    size_adults integer,
    size_children_u5 integer,
    size_school_age integer,
    size_elderly integer,
    number_of_female_members integer,
    number_of_male_members integer,
    elderly_member_present boolean,
    dwelling_type character varying,
    roof_material character varying,
    wall_material character varying,
    floor_material character varying,
    tenure_status character varying,
    rooms_count integer,
    overcrowding_indicator numeric,
    water_source_type character varying,
    water_distance_minutes integer,
    sanitation_type character varying,
    lighting_source character varying,
    cooking_fuel_type character varying,
    mobile_phone_type character varying
);


--
-- Name: dbt_intake_form_individual_disabilities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_intake_form_individual_disabilities (
    submission_id uuid NOT NULL,
    application_reference character varying,
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    disability_domain character varying,
    disability_severity character varying
);


--
-- Name: dbt_intake_form_individual_land; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_intake_form_individual_land (
    submission_id uuid NOT NULL,
    application_reference character varying,
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    land_access boolean,
    land_size numeric,
    productive_assets json
);


--
-- Name: dbt_intake_form_individual_livelihoods; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_intake_form_individual_livelihoods (
    submission_id uuid NOT NULL,
    application_reference character varying,
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    primary_livelihood character varying,
    secondary_livelihood character varying,
    employment_status character varying,
    coping_strategies_index integer,
    mobile_phone_type character varying
);


--
-- Name: dbt_intake_form_individual_livestock; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_intake_form_individual_livestock (
    submission_id uuid NOT NULL,
    application_reference character varying,
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    livestock_species character varying,
    livestock_counts character varying
);


--
-- Name: dbt_intake_form_individual_programs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_intake_form_individual_programs (
    submission_id uuid NOT NULL,
    application_reference character varying,
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    program_name character varying,
    program_start_date date,
    program_exit_date date
);


--
-- Name: dbt_intake_form_individual_shocks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_intake_form_individual_shocks (
    submission_id uuid NOT NULL,
    application_reference character varying,
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    shock_type character varying,
    shock_date date,
    shock_period character varying,
    coping_strategy character varying
);


--
-- Name: dbt_intake_form_individual_vulnerability; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_intake_form_individual_vulnerability (
    submission_id uuid NOT NULL,
    application_reference character varying,
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    disability_status character varying,
    orphanhood_flag boolean,
    chronic_illness_flag boolean,
    displacement_status character varying,
    pastoralist_classification character varying,
    high_mobility_indicator boolean,
    plw_status boolean,
    plw_status_date date
);


--
-- Name: dbt_intake_form_individuals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_intake_form_individuals (
    submission_id uuid NOT NULL,
    application_reference character varying,
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    foundational_id character varying,
    first_name character varying,
    middle_name character varying,
    last_name character varying,
    given_name character varying,
    prefix character varying,
    suffix character varying,
    gender character varying,
    birth_date date,
    phone_numbers jsonb,
    emails jsonb,
    marital_status character varying,
    occupation character varying,
    income_level character varying,
    language_code character varying,
    education_level character varying,
    registration_date date,
    latitude double precision,
    longitude double precision,
    altitude double precision,
    plus_code character varying,
    address_line_1 character varying,
    address_line_2 character varying,
    postal_code character varying,
    country_code character varying,
    geo_lowest_level_value_id character varying,
    geo_code_hierarchy_json jsonb,
    foundational_id_masked character varying,
    foundational_id_verification_status character varying,
    identity_evidence_type character varying,
    legacy_program_ids json,
    full_name character varying,
    alias_names json,
    estimated_age integer,
    age_method character varying,
    citizenship_category character varying,
    relationship_to_head character varying,
    residency_status character varying,
    dependency_indicator boolean,
    preferred_contact_method character varying,
    contact_person_name character varying,
    disability_status character varying,
    plw_status boolean,
    plw_status_date date,
    orphanhood_flag boolean,
    chronic_illness_flag boolean,
    displacement_status character varying,
    pastoralist_classification character varying,
    high_mobility_indicator boolean,
    primary_livelihood character varying,
    secondary_livelihood character varying,
    employment_status character varying,
    coping_strategies_index integer
);


--
-- Name: dbt_intake_form_submissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_intake_form_submissions (
    submission_id uuid NOT NULL,
    application_reference character varying NOT NULL,
    form_id character varying NOT NULL,
    register_id character varying NOT NULL,
    draft_status character varying NOT NULL,
    approval_status character varying NOT NULL,
    approved_by character varying,
    approved_at timestamp without time zone,
    remarks text,
    finalized_at timestamp without time zone,
    first_created_at timestamp without time zone NOT NULL,
    last_updated_at timestamp without time zone,
    created_by character varying NOT NULL,
    submission_source character varying NOT NULL,
    partner_id character varying,
    register_ingest_process_status character varying NOT NULL,
    register_ingest_processed_timestamp timestamp without time zone,
    register_ingest_process_attempts integer NOT NULL,
    register_ingest_process_last_error_code text,
    number_of_verifications_required integer NOT NULL,
    number_of_verifications_done integer NOT NULL,
    deduplication_status_vs_intake_forms character varying NOT NULL,
    deduplication_intake_forms_process_timestamp timestamp without time zone,
    deduplication_intake_forms_attempts integer NOT NULL,
    deduplication_intake_forms_error text,
    deduplication_status_vs_register character varying NOT NULL,
    deduplication_register_process_timestamp timestamp without time zone,
    deduplication_register_forms_attempts integer NOT NULL,
    deduplication_register_error text,
    awe_request_id character varying,
    awe_request_status_summary text
);


--
-- Name: dbt_intake_form_ui_tab_sections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_intake_form_ui_tab_sections (
    tab_section_id character varying NOT NULL,
    tab_id character varying NOT NULL,
    section_id character varying NOT NULL,
    section_order integer NOT NULL
);


--
-- Name: dbt_intake_form_ui_tabs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_intake_form_ui_tabs (
    tab_id character varying NOT NULL,
    form_id character varying NOT NULL,
    tab_label character varying NOT NULL,
    tab_order integer NOT NULL
);


--
-- Name: dbt_intake_section_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_intake_section_documents (
    submission_id uuid NOT NULL,
    document_id character varying NOT NULL,
    section_id character varying NOT NULL,
    label character varying NOT NULL
);


--
-- Name: dbt_register_change_request_payloads; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_change_request_payloads (
    change_request_id character varying NOT NULL,
    change_payload json NOT NULL,
    search_text text
);


--
-- Name: dbt_register_change_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_change_requests (
    change_request_id character varying NOT NULL,
    record_name character varying,
    register_id character varying NOT NULL,
    tab_id character varying NOT NULL,
    section_id character varying NOT NULL,
    section_register_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    no_of_verifications_required integer NOT NULL,
    no_of_verifications_done integer NOT NULL,
    deduplication_register_status character varying NOT NULL,
    deduplication_register_failure_reason character varying,
    deduplication_change_request_status character varying NOT NULL,
    deduplication_change_request_failure_reason character varying,
    remarks text,
    approval_status character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    approved_at timestamp without time zone,
    created_by character varying NOT NULL,
    approved_by character varying,
    change_request_source character varying NOT NULL,
    source_partner_id character varying NOT NULL,
    awe_request_id character varying,
    awe_request_status_summary text
);


--
-- Name: dbt_register_definitions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_definitions (
    register_id character varying NOT NULL,
    register_mnemonic character varying NOT NULL,
    register_subject character varying,
    register_description text,
    master_register_id character varying,
    register_rank integer,
    functional_id_generation_required boolean NOT NULL,
    register_purpose character varying NOT NULL,
    program_id character varying,
    program_mnemonic character varying,
    register_icon text,
    has_image boolean NOT NULL,
    dedup_is_enabled boolean NOT NULL,
    dedup_threshold_score double precision,
    completion_score_required boolean NOT NULL,
    outgest_applicable boolean NOT NULL,
    requires_registrant_authentication boolean NOT NULL,
    registrant_authentication_validity_days integer,
    registrant_re_auth_warning_days_before integer
);


--
-- Name: dbt_register_document_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_document_history (
    document_history_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    section_id character varying NOT NULL,
    document_id character varying NOT NULL,
    label character varying NOT NULL,
    change_request_id character varying,
    submission_id character varying,
    change_request_source character varying,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    approved_by character varying NOT NULL,
    approved_at timestamp without time zone NOT NULL
);


--
-- Name: dbt_register_export_data_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_export_data_queue (
    export_id character varying NOT NULL,
    register_id character varying NOT NULL,
    requested_by character varying NOT NULL,
    queued_at timestamp without time zone NOT NULL,
    export_format character varying NOT NULL,
    selection_mode character varying NOT NULL,
    selected_internal_record_ids jsonb,
    search_text text,
    filter_by jsonb,
    sort_by character varying,
    policy_mnemonics jsonb,
    data_policies jsonb,
    batch_size integer NOT NULL,
    last_processed_offset integer NOT NULL,
    export_status character varying NOT NULL,
    export_no_of_attempts integer NOT NULL,
    export_latest_timestamp timestamp without time zone,
    export_latest_error_code text,
    file_object_name text,
    file_presigned_url text,
    file_url_expires_at timestamp without time zone,
    total_records_exported integer
);


--
-- Name: dbt_register_history_household_assets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_history_household_assets (
    history_record_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    tab_id character varying NOT NULL,
    section_id character varying NOT NULL,
    change_request_id character varying,
    submission_id character varying,
    change_request_source character varying NOT NULL,
    is_primary_section boolean NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    subject_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    approved_by character varying NOT NULL,
    approved_at timestamp without time zone NOT NULL,
    asset_type character varying,
    asset_category character varying,
    quantity integer,
    size_value numeric,
    size_unit character varying,
    size_band character varying,
    details json
);


--
-- Name: dbt_register_history_household_housing_and_services; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_history_household_housing_and_services (
    history_record_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    tab_id character varying NOT NULL,
    section_id character varying NOT NULL,
    change_request_id character varying,
    submission_id character varying,
    change_request_source character varying NOT NULL,
    is_primary_section boolean NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    subject_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    approved_by character varying NOT NULL,
    approved_at timestamp without time zone NOT NULL,
    dwelling_type character varying,
    roof_material character varying,
    wall_material character varying,
    floor_material character varying,
    tenure_status character varying,
    water_source_type character varying,
    water_distance_minutes integer,
    sanitation_type character varying,
    lighting_source character varying,
    cooking_fuel_type character varying
);


--
-- Name: dbt_register_history_household_programs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_history_household_programs (
    history_record_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    tab_id character varying NOT NULL,
    section_id character varying NOT NULL,
    change_request_id character varying,
    submission_id character varying,
    change_request_source character varying NOT NULL,
    is_primary_section boolean NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    subject_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    approved_by character varying NOT NULL,
    approved_at timestamp without time zone NOT NULL,
    program_name character varying,
    program_start_date date,
    program_exit_date date
);


--
-- Name: dbt_register_history_households; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_history_households (
    history_record_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    tab_id character varying NOT NULL,
    section_id character varying NOT NULL,
    change_request_id character varying,
    submission_id character varying,
    change_request_source character varying NOT NULL,
    is_primary_section boolean NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    subject_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    approved_by character varying NOT NULL,
    approved_at timestamp without time zone NOT NULL,
    latitude double precision,
    longitude double precision,
    altitude double precision,
    plus_code character varying,
    address_line_1 character varying,
    address_line_2 character varying,
    postal_code character varying,
    country_code character varying,
    geo_lowest_level_value_id character varying,
    geo_code_hierarchy_json jsonb,
    household_head_internal_record_id character varying,
    household_head_name character varying,
    headship_type character varying,
    husband_dead boolean DEFAULT false,
    husband_dead_date date,
    size_total integer,
    size_adults integer,
    size_children_u5 integer,
    size_school_age integer,
    size_elderly integer,
    number_of_female_members integer,
    number_of_male_members integer,
    elderly_member_present boolean,
    dwelling_type character varying,
    roof_material character varying,
    wall_material character varying,
    floor_material character varying,
    tenure_status character varying,
    rooms_count integer,
    overcrowding_indicator numeric,
    water_source_type character varying,
    water_distance_minutes integer,
    sanitation_type character varying,
    lighting_source character varying,
    cooking_fuel_type character varying,
    mobile_phone_type character varying
);


--
-- Name: dbt_register_history_individual_disabilities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_history_individual_disabilities (
    history_record_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    tab_id character varying NOT NULL,
    section_id character varying NOT NULL,
    change_request_id character varying,
    submission_id character varying,
    change_request_source character varying NOT NULL,
    is_primary_section boolean NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    subject_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    approved_by character varying NOT NULL,
    approved_at timestamp without time zone NOT NULL,
    disability_domain character varying,
    disability_severity character varying
);


--
-- Name: dbt_register_history_individual_land; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_history_individual_land (
    history_record_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    tab_id character varying NOT NULL,
    section_id character varying NOT NULL,
    change_request_id character varying,
    submission_id character varying,
    change_request_source character varying NOT NULL,
    is_primary_section boolean NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    subject_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    approved_by character varying NOT NULL,
    approved_at timestamp without time zone NOT NULL,
    land_access boolean,
    land_size numeric,
    productive_assets json
);


--
-- Name: dbt_register_history_individual_livelihoods; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_history_individual_livelihoods (
    history_record_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    tab_id character varying NOT NULL,
    section_id character varying NOT NULL,
    change_request_id character varying,
    submission_id character varying,
    change_request_source character varying NOT NULL,
    is_primary_section boolean NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    subject_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    approved_by character varying NOT NULL,
    approved_at timestamp without time zone NOT NULL,
    primary_livelihood character varying,
    secondary_livelihood character varying,
    employment_status character varying,
    coping_strategies_index integer,
    mobile_phone_type character varying
);


--
-- Name: dbt_register_history_individual_livestock; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_history_individual_livestock (
    history_record_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    tab_id character varying NOT NULL,
    section_id character varying NOT NULL,
    change_request_id character varying,
    submission_id character varying,
    change_request_source character varying NOT NULL,
    is_primary_section boolean NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    subject_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    approved_by character varying NOT NULL,
    approved_at timestamp without time zone NOT NULL,
    livestock_species character varying,
    livestock_counts character varying
);


--
-- Name: dbt_register_history_individual_programs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_history_individual_programs (
    history_record_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    tab_id character varying NOT NULL,
    section_id character varying NOT NULL,
    change_request_id character varying,
    submission_id character varying,
    change_request_source character varying NOT NULL,
    is_primary_section boolean NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    subject_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    approved_by character varying NOT NULL,
    approved_at timestamp without time zone NOT NULL,
    program_name character varying,
    program_start_date date,
    program_exit_date date
);


--
-- Name: dbt_register_history_individual_shocks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_history_individual_shocks (
    history_record_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    tab_id character varying NOT NULL,
    section_id character varying NOT NULL,
    change_request_id character varying,
    submission_id character varying,
    change_request_source character varying NOT NULL,
    is_primary_section boolean NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    subject_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    approved_by character varying NOT NULL,
    approved_at timestamp without time zone NOT NULL,
    shock_type character varying,
    shock_date date,
    shock_period character varying,
    coping_strategy character varying
);


--
-- Name: dbt_register_history_individual_vulnerability; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_history_individual_vulnerability (
    history_record_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    tab_id character varying NOT NULL,
    section_id character varying NOT NULL,
    change_request_id character varying,
    submission_id character varying,
    change_request_source character varying NOT NULL,
    is_primary_section boolean NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    subject_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    approved_by character varying NOT NULL,
    approved_at timestamp without time zone NOT NULL,
    disability_status character varying,
    orphanhood_flag boolean,
    chronic_illness_flag boolean,
    displacement_status character varying,
    pastoralist_classification character varying,
    high_mobility_indicator boolean,
    plw_status boolean,
    plw_status_date date
);


--
-- Name: dbt_register_history_individuals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_history_individuals (
    history_record_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    tab_id character varying NOT NULL,
    section_id character varying NOT NULL,
    change_request_id character varying,
    submission_id character varying,
    change_request_source character varying NOT NULL,
    is_primary_section boolean NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    subject_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    approved_by character varying NOT NULL,
    approved_at timestamp without time zone NOT NULL,
    foundational_id character varying,
    first_name character varying,
    middle_name character varying,
    last_name character varying,
    given_name character varying,
    prefix character varying,
    suffix character varying,
    gender character varying,
    birth_date date,
    phone_numbers jsonb,
    emails jsonb,
    marital_status character varying,
    occupation character varying,
    income_level character varying,
    language_code character varying,
    education_level character varying,
    registration_date date,
    latitude double precision,
    longitude double precision,
    altitude double precision,
    plus_code character varying,
    address_line_1 character varying,
    address_line_2 character varying,
    postal_code character varying,
    country_code character varying,
    geo_lowest_level_value_id character varying,
    geo_code_hierarchy_json jsonb,
    foundational_id_masked character varying,
    foundational_id_verification_status character varying,
    identity_evidence_type character varying,
    legacy_program_ids json,
    full_name character varying,
    alias_names json,
    estimated_age integer,
    age_method character varying,
    citizenship_category character varying,
    relationship_to_head character varying,
    residency_status character varying,
    dependency_indicator boolean,
    preferred_contact_method character varying,
    contact_person_name character varying,
    disability_status character varying,
    plw_status boolean,
    plw_status_date date,
    orphanhood_flag boolean,
    chronic_illness_flag boolean,
    displacement_status character varying,
    pastoralist_classification character varying,
    high_mobility_indicator boolean,
    primary_livelihood character varying,
    secondary_livelihood character varying,
    employment_status character varying,
    coping_strategies_index integer
);


--
-- Name: dbt_register_household_assets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_household_assets (
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    asset_type character varying,
    asset_category character varying,
    quantity integer,
    size_value numeric,
    size_unit character varying,
    size_band character varying,
    details json
);


--
-- Name: dbt_register_household_housing_and_services; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_household_housing_and_services (
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    dwelling_type character varying,
    roof_material character varying,
    wall_material character varying,
    floor_material character varying,
    tenure_status character varying,
    water_source_type character varying,
    water_distance_minutes integer,
    sanitation_type character varying,
    lighting_source character varying,
    cooking_fuel_type character varying
);


--
-- Name: dbt_register_household_programs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_household_programs (
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    program_name character varying,
    program_start_date date,
    program_exit_date date
);


--
-- Name: dbt_register_households; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_households (
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    latitude double precision,
    longitude double precision,
    altitude double precision,
    plus_code character varying,
    address_line_1 character varying,
    address_line_2 character varying,
    postal_code character varying,
    country_code character varying,
    geo_lowest_level_value_id character varying,
    geo_code_hierarchy_json jsonb,
    household_head_internal_record_id character varying,
    household_head_name character varying,
    headship_type character varying,
    husband_dead boolean DEFAULT false,
    husband_dead_date date,
    size_total integer,
    size_adults integer,
    size_children_u5 integer,
    size_school_age integer,
    size_elderly integer,
    number_of_female_members integer,
    number_of_male_members integer,
    elderly_member_present boolean,
    dwelling_type character varying,
    roof_material character varying,
    wall_material character varying,
    floor_material character varying,
    tenure_status character varying,
    rooms_count integer,
    overcrowding_indicator numeric,
    water_source_type character varying,
    water_distance_minutes integer,
    sanitation_type character varying,
    lighting_source character varying,
    cooking_fuel_type character varying,
    mobile_phone_type character varying
);


--
-- Name: dbt_register_individual_disabilities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_individual_disabilities (
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    disability_domain character varying,
    disability_severity character varying
);


--
-- Name: dbt_register_individual_land; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_individual_land (
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    land_access boolean,
    land_size numeric,
    productive_assets json
);


--
-- Name: dbt_register_individual_livelihoods; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_individual_livelihoods (
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    primary_livelihood character varying,
    secondary_livelihood character varying,
    employment_status character varying,
    coping_strategies_index integer,
    mobile_phone_type character varying
);


--
-- Name: dbt_register_individual_livestock; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_individual_livestock (
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    livestock_species character varying,
    livestock_counts character varying
);


--
-- Name: dbt_register_individual_programs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_individual_programs (
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    program_name character varying,
    program_start_date date,
    program_exit_date date
);


--
-- Name: dbt_register_individual_shocks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_individual_shocks (
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    shock_type character varying,
    shock_date date,
    shock_period character varying,
    coping_strategy character varying
);


--
-- Name: dbt_register_individual_vulnerability; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_individual_vulnerability (
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    disability_status character varying,
    orphanhood_flag boolean,
    chronic_illness_flag boolean,
    displacement_status character varying,
    pastoralist_classification character varying,
    high_mobility_indicator boolean,
    plw_status boolean,
    plw_status_date date
);


--
-- Name: dbt_register_individuals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_individuals (
    internal_record_id character varying NOT NULL,
    functional_record_id character varying,
    link_internal_record_id character varying,
    link_foundational_id character varying,
    record_name character varying,
    record_image_document_id text,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_approved_at timestamp without time zone NOT NULL,
    last_approved_by character varying NOT NULL,
    search_text text,
    record_status character varying NOT NULL,
    record_status_reason character varying,
    foundational_id character varying,
    first_name character varying,
    middle_name character varying,
    last_name character varying,
    given_name character varying,
    prefix character varying,
    suffix character varying,
    gender character varying,
    birth_date date,
    phone_numbers jsonb,
    emails jsonb,
    marital_status character varying,
    occupation character varying,
    income_level character varying,
    language_code character varying,
    education_level character varying,
    registration_date date,
    latitude double precision,
    longitude double precision,
    altitude double precision,
    plus_code character varying,
    address_line_1 character varying,
    address_line_2 character varying,
    postal_code character varying,
    country_code character varying,
    geo_lowest_level_value_id character varying,
    geo_code_hierarchy_json jsonb,
    foundational_id_masked character varying,
    foundational_id_verification_status character varying,
    identity_evidence_type character varying,
    legacy_program_ids json,
    full_name character varying,
    alias_names json,
    estimated_age integer,
    age_method character varying,
    citizenship_category character varying,
    relationship_to_head character varying,
    residency_status character varying,
    dependency_indicator boolean,
    preferred_contact_method character varying,
    contact_person_name character varying,
    disability_status character varying,
    plw_status boolean,
    plw_status_date date,
    orphanhood_flag boolean,
    chronic_illness_flag boolean,
    displacement_status character varying,
    pastoralist_classification character varying,
    high_mobility_indicator boolean,
    primary_livelihood character varying,
    secondary_livelihood character varying,
    employment_status character varying,
    coping_strategies_index integer
);


--
-- Name: dbt_register_schemas; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_schemas (
    register_id character varying NOT NULL,
    deduplicate_schema json,
    search_result_schema json,
    filter_schema json
);


--
-- Name: dbt_register_score_contributing_attributes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_score_contributing_attributes (
    contributing_attribute_id character varying NOT NULL,
    register_mnemonic character varying NOT NULL,
    score_type character varying NOT NULL,
    attribute_name character varying NOT NULL,
    attribute_computation_required boolean NOT NULL,
    attribute_computation_value json,
    attribute_weightage double precision NOT NULL
);


--
-- Name: dbt_register_score_definitions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_score_definitions (
    score_definition_id character varying NOT NULL,
    register_mnemonic character varying NOT NULL,
    score_type character varying NOT NULL,
    is_enabled boolean NOT NULL
);


--
-- Name: dbt_register_score_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_score_history (
    internal_record_id character varying NOT NULL,
    register_id character varying NOT NULL,
    score_type character varying NOT NULL,
    score_definition_id character varying NOT NULL,
    link_internal_record_id character varying,
    triggered_by_cr_id character varying NOT NULL,
    triggered_by_submission_id character varying,
    computed_score double precision NOT NULL,
    computed_at timestamp without time zone NOT NULL
);


--
-- Name: dbt_register_scores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_scores (
    internal_record_id character varying NOT NULL,
    register_id character varying NOT NULL,
    score_type character varying NOT NULL,
    score_definition_id character varying NOT NULL,
    link_internal_record_id character varying,
    triggered_by_cr_id character varying NOT NULL,
    triggered_by_submission_id character varying,
    computed_score double precision NOT NULL,
    computed_at timestamp without time zone NOT NULL
);


--
-- Name: dbt_register_section_completion_score; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_section_completion_score (
    id character varying NOT NULL,
    register_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    section_id character varying NOT NULL,
    computed_section_completion_score double precision NOT NULL,
    computed_timestamp timestamp without time zone NOT NULL
);


--
-- Name: dbt_register_section_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_section_documents (
    internal_record_id character varying NOT NULL,
    document_id character varying NOT NULL,
    section_id character varying NOT NULL,
    label character varying NOT NULL
);


--
-- Name: dbt_register_sections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_sections (
    register_id character varying NOT NULL,
    section_id character varying NOT NULL,
    section_register_id character varying NOT NULL,
    is_core_section boolean NOT NULL,
    section_mnemonic character varying NOT NULL,
    section_description text,
    documents_required boolean NOT NULL,
    no_of_verifications_required integer NOT NULL,
    is_list boolean NOT NULL,
    section_weightage double precision NOT NULL,
    section_ui_schema jsonb,
    cr_auto_approve_for_bene_portal boolean NOT NULL,
    cr_auto_approve_for_agent_portal boolean NOT NULL,
    cr_auto_approve_for_staff_portal boolean NOT NULL,
    cr_auto_approve_for_partner boolean NOT NULL
);


--
-- Name: dbt_register_ui_tab_sections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_ui_tab_sections (
    tab_section_id character varying NOT NULL,
    register_id character varying NOT NULL,
    tab_id character varying NOT NULL,
    section_id character varying NOT NULL,
    section_order integer NOT NULL
);


--
-- Name: dbt_register_ui_tabs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_ui_tabs (
    tab_id character varying NOT NULL,
    register_id character varying NOT NULL,
    tab_label character varying NOT NULL,
    tab_order integer NOT NULL,
    is_active boolean NOT NULL
);


--
-- Name: dbt_register_verifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_register_verifications (
    verification_id character varying NOT NULL,
    register_id character varying NOT NULL,
    internal_record_id character varying,
    section_id character varying,
    change_request_id character varying,
    submission_id character varying,
    verified_by character varying NOT NULL,
    verified_at timestamp without time zone NOT NULL,
    verification_observations text,
    is_approved boolean NOT NULL
);


--
-- Name: dbt_registrant_authentication_providers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_registrant_authentication_providers (
    provider_id character varying NOT NULL,
    register_id character varying NOT NULL,
    provider_name character varying NOT NULL,
    provider_description character varying,
    adapter_name character varying NOT NULL,
    server_metadata_url character varying,
    authorization_endpoint character varying,
    token_endpoint character varying,
    userinfo_endpoint character varying,
    jwks_endpoint character varying,
    introspection_endpoint character varying,
    client_id character varying NOT NULL,
    client_secret character varying,
    client_private_key bytea,
    token_endpoint_auth_method character varying NOT NULL,
    oauth_callback_url character varying NOT NULL,
    keymanager_sign_app_id character varying,
    provider_config jsonb,
    display_order integer NOT NULL,
    is_active boolean NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: dbt_registrant_authentications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_registrant_authentications (
    authentication_id character varying NOT NULL,
    register_id character varying NOT NULL,
    internal_record_id character varying NOT NULL,
    provider_id character varying NOT NULL,
    initiated_by_staff_id character varying NOT NULL,
    initiated_at timestamp without time zone NOT NULL,
    status character varying NOT NULL,
    user_claims character varying,
    authentication_method character varying,
    claim_verifications jsonb,
    token_hash character varying,
    token_expires_at timestamp without time zone,
    expiry_at timestamp without time zone,
    failure_reason character varying,
    completed_at timestamp without time zone,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: dbt_registry_awe_policy_configurations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_registry_awe_policy_configurations (
    awe_policy_config_id character varying NOT NULL,
    policy_scope character varying NOT NULL,
    register_id character varying NOT NULL,
    intake_form_id character varying,
    section_id character varying,
    policy_type character varying NOT NULL,
    policy_key character varying NOT NULL,
    context_field_names json
);


--
-- Name: dbt_registry_configuration; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_registry_configuration (
    configuration_id character varying NOT NULL,
    registry_name character varying NOT NULL,
    registry_logo text,
    registry_favicon text,
    registry_theme_id character varying,
    registry_language_id character varying
);


--
-- Name: dbt_registry_data_policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_registry_data_policies (
    policy_id character varying NOT NULL,
    policy_mnemonic character varying NOT NULL,
    policy_description character varying,
    register_id character varying,
    policy_target character varying NOT NULL,
    policy_type character varying NOT NULL,
    policy_filter_expression json NOT NULL
);


--
-- Name: dbt_registry_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_registry_documents (
    document_id character varying NOT NULL,
    document_store_id character varying NOT NULL,
    bucket character varying(17) NOT NULL,
    source_filename character varying NOT NULL,
    created_by character varying NOT NULL,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: dbt_registry_import_file_configurations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_registry_import_file_configurations (
    import_file_configuration_id character varying NOT NULL,
    register_id character varying NOT NULL,
    form_id character varying NOT NULL,
    data_model_id character varying NOT NULL,
    import_file_template_mnemonic character varying NOT NULL,
    import_file_template_description text NOT NULL
);


--
-- Name: dbt_registry_vc_configurations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_registry_vc_configurations (
    vc_config_id character varying NOT NULL,
    register_id character varying NOT NULL,
    intake_form_id character varying,
    data_model_id character varying,
    vc_mnemonic character varying NOT NULL,
    descriptor_schema jsonb NOT NULL
);


--
-- Name: dbt_score_compute_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbt_score_compute_queue (
    queue_id character varying NOT NULL,
    register_id character varying NOT NULL,
    link_internal_record_id character varying,
    score_definition_id character varying NOT NULL,
    score_type character varying NOT NULL,
    change_request_id character varying,
    submission_id character varying,
    contributing_attribute_values json NOT NULL,
    compute_status character varying NOT NULL,
    compute_no_of_attempts integer NOT NULL,
    compute_latest_timestamp timestamp without time zone,
    compute_latest_error_code character varying
);


--
-- Name: import_file_process_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.import_file_process_log (
    import_file_record_id character varying NOT NULL,
    import_file_id character varying NOT NULL,
    document_id character varying NOT NULL,
    record_number integer NOT NULL,
    ingestion_timestamp timestamp without time zone NOT NULL
);


--
-- Name: import_file_process_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.import_file_process_queue (
    import_file_id character varying NOT NULL,
    document_id character varying NOT NULL,
    data_model_id character varying NOT NULL,
    register_id character varying NOT NULL,
    intake_form_id character varying NOT NULL,
    queued_at timestamp without time zone NOT NULL,
    queued_by character varying,
    intake_form_ingestion_status character varying NOT NULL,
    intake_form_ingestion_timestamp timestamp without time zone,
    intake_form_ingestion_attempts integer NOT NULL,
    intake_form_ingestion_error character varying,
    number_of_records_present integer,
    number_of_records_ingested integer
);


--
-- Name: incoming_classified_data; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.incoming_classified_data (
    ingest_id character varying NOT NULL,
    data_model_id character varying NOT NULL,
    partner_id character varying NOT NULL,
    register_id character varying NOT NULL,
    pipeline_action character varying NOT NULL,
    section_id character varying,
    internal_record_id character varying,
    change_request_id character varying,
    intake_form_id character varying,
    semantic_pattern_id character varying NOT NULL,
    classified_date_time timestamp without time zone NOT NULL,
    transformation_status character varying NOT NULL,
    transformation_date_time timestamp without time zone,
    transformation_number_of_attempts integer NOT NULL,
    transformation_latest_error_code character varying,
    ingestion_status character varying NOT NULL,
    ingestion_date_time timestamp without time zone,
    ingestion_number_of_attempts integer NOT NULL,
    ingestion_latest_error_code character varying,
    intake_form_submission_id character varying
);


--
-- Name: incoming_enriched_transformed_data; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.incoming_enriched_transformed_data (
    ingest_id character varying NOT NULL,
    enriched_data_json json,
    enriched_data_xml text,
    transformed_data_json json,
    transformed_data_xml text
);


--
-- Name: incoming_model_key_paths; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.incoming_model_key_paths (
    key_path_id character varying NOT NULL,
    data_model_id character varying NOT NULL,
    key_path_for_message_id character varying NOT NULL,
    key_path_for_sender character varying NOT NULL,
    key_path_for_signature character varying NOT NULL,
    key_path_for_signature_payload character varying NOT NULL,
    is_list boolean NOT NULL,
    key_path_for_list_elements character varying NOT NULL
);


--
-- Name: incoming_model_register_semantic_patterns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.incoming_model_register_semantic_patterns (
    register_semantic_pattern_id character varying NOT NULL,
    data_model_id character varying NOT NULL,
    register_id character varying NOT NULL,
    pattern_for_register character varying NOT NULL,
    key_path_for_record_identifier character varying NOT NULL
);


--
-- Name: incoming_model_semantic_patterns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.incoming_model_semantic_patterns (
    semantic_pattern_id character varying NOT NULL,
    data_model_id character varying NOT NULL,
    register_id character varying NOT NULL,
    intake_form_id character varying,
    section_id character varying,
    pattern_for_register character varying,
    pattern_for_intake_form character varying,
    pattern_for_section character varying,
    key_path_for_business_payload character varying NOT NULL,
    raw_payload_enricher_class character varying NOT NULL
);


--
-- Name: incoming_raw_data; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.incoming_raw_data (
    ingest_id character varying NOT NULL,
    partner_id character varying NOT NULL,
    data_model_id character varying NOT NULL,
    ingest_message_id character varying NOT NULL,
    ingest_correlation_id character varying NOT NULL,
    receipt_date_time timestamp without time zone NOT NULL,
    classification_status character varying NOT NULL,
    classification_date_time timestamp without time zone,
    classification_number_of_attempts integer NOT NULL,
    classification_latest_error_code character varying
);


--
-- Name: incoming_raw_data_payloads; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.incoming_raw_data_payloads (
    ingest_id character varying NOT NULL,
    raw_data_json json,
    raw_data_xml text,
    raw_data_text text
);


--
-- Name: incoming_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.incoming_templates (
    template_id character varying NOT NULL,
    register_id character varying NOT NULL,
    data_model_id character varying NOT NULL,
    template_document_id character varying NOT NULL,
    jsonld_expansion_required boolean NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: ndbt_geography_areas; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ndbt_geography_areas (
    area_id text NOT NULL,
    area_name text NOT NULL,
    area_level text NOT NULL,
    zone_id text NOT NULL,
    zone_name text NOT NULL,
    state_id text NOT NULL,
    state_name text NOT NULL,
    country_code text NOT NULL,
    parent_id text NOT NULL
);


--
-- Name: ndbt_record_geography; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.ndbt_record_geography AS
 WITH records AS (
         SELECT 'individual'::text AS record_type,
            dbt_register_individuals.internal_record_id,
            dbt_register_individuals.record_status,
            dbt_register_individuals.country_code,
            dbt_register_individuals.geo_lowest_level_value_id,
            dbt_register_individuals.latitude,
            dbt_register_individuals.longitude,
            dbt_register_individuals.geo_code_hierarchy_json
           FROM public.dbt_register_individuals
        UNION ALL
         SELECT 'household'::text AS record_type,
            dbt_register_households.internal_record_id,
            dbt_register_households.record_status,
            dbt_register_households.country_code,
            dbt_register_households.geo_lowest_level_value_id,
            dbt_register_households.latitude,
            dbt_register_households.longitude,
            dbt_register_households.geo_code_hierarchy_json
           FROM public.dbt_register_households
        )
 SELECT r.record_type,
    r.internal_record_id,
    r.record_status,
    r.country_code,
    a.zone_id,
    a.zone_name,
    a.state_id,
    a.state_name,
        CASE
            WHEN (a.area_level = 'lga'::text) THEN a.area_id
            ELSE NULL::text
        END AS lga_id,
        CASE
            WHEN (a.area_level = 'lga'::text) THEN a.area_name
            ELSE NULL::text
        END AS lga_name,
    ((r.geo_code_hierarchy_json -> 'karnatakadbt'::text) ->> 'ward'::text) AS ward,
    COALESCE(a.area_level, 'unknown'::text) AS administrative_level,
        CASE
            WHEN (((r.latitude >= ('-90'::integer)::double precision) AND (r.latitude <= (90)::double precision)) AND ((r.longitude >= ('-180'::integer)::double precision) AND (r.longitude <= (180)::double precision))) THEN r.latitude
            ELSE NULL::double precision
        END AS latitude,
        CASE
            WHEN (((r.latitude >= ('-90'::integer)::double precision) AND (r.latitude <= (90)::double precision)) AND ((r.longitude >= ('-180'::integer)::double precision) AND (r.longitude <= (180)::double precision))) THEN r.longitude
            ELSE NULL::double precision
        END AS longitude,
    COALESCE(((r.geo_code_hierarchy_json -> 'karnatakadbt'::text) ->> 'coordinate_source'::text), 'registry_unverified'::text) AS coordinate_source,
    false AS coordinate_verified,
    'KarnatakaDBT project identifiers, not official P-codes'::text AS code_system
   FROM (records r
     LEFT JOIN public.ndbt_geography_areas a ON (((a.area_id = (r.geo_lowest_level_value_id)::text) AND ((r.country_code)::text = ANY ((ARRAY['IND'::character varying, 'IN'::character varying])::text[])))));


--
-- Name: ndbt_geography_record_counts; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.ndbt_geography_record_counts AS
 SELECT record_type,
    zone_id,
    zone_name,
    state_id,
    state_name,
    lga_id,
    lga_name,
    administrative_level,
    count(*) AS record_count,
    count(*) FILTER (WHERE ((latitude IS NOT NULL) AND (longitude IS NOT NULL))) AS coordinates_present
   FROM public.ndbt_record_geography
  GROUP BY record_type, zone_id, zone_name, state_id, state_name, lga_id, lga_name, administrative_level;


--
-- Name: outgoing_raw_data; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outgoing_raw_data (
    outgest_id character varying NOT NULL,
    payload_id character varying NOT NULL,
    change_request_id character varying,
    intake_form_submission_id character varying,
    internal_record_id character varying NOT NULL,
    register_id character varying NOT NULL,
    data_model_id character varying NOT NULL,
    topic_id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    changed_by character varying NOT NULL,
    changed_at timestamp without time zone NOT NULL,
    approved_by character varying,
    approved_at timestamp without time zone,
    changed_by_partner_id character varying,
    transformation_status character varying NOT NULL,
    transformation_datetime timestamp without time zone,
    transformation_latest_error_code character varying,
    transformation_number_of_attempts integer NOT NULL,
    publish_status character varying,
    publish_datetime timestamp without time zone,
    publish_latest_error_code character varying,
    publish_number_of_attempts integer NOT NULL
);


--
-- Name: outgoing_raw_data_payloads; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outgoing_raw_data_payloads (
    payload_id character varying NOT NULL,
    change_request_id character varying,
    intake_form_submission_id character varying,
    raw_data_json jsonb,
    raw_data_xml text,
    raw_data_text text
);


--
-- Name: outgoing_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outgoing_templates (
    template_id character varying NOT NULL,
    data_model_id character varying NOT NULL,
    register_id character varying NOT NULL,
    template_document_id character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: outgoing_topics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outgoing_topics (
    topic_id character varying NOT NULL,
    register_id character varying NOT NULL,
    data_model_id character varying NOT NULL,
    websub_topic character varying NOT NULL,
    description character varying,
    is_active boolean NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone,
    websub_register_status character varying NOT NULL,
    websub_register_datetime timestamp without time zone,
    websub_register_number_of_attempts integer NOT NULL,
    websub_register_latest_error_code character varying
);


--
-- Name: outgoing_transformed_data_payloads; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outgoing_transformed_data_payloads (
    outgest_id character varying NOT NULL,
    payload_id character varying NOT NULL,
    change_request_id character varying,
    intake_form_submission_id character varying,
    transformed_data_json jsonb,
    transformed_data_xml text
);


--
-- Name: registry_languages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.registry_languages (
    language_id character varying NOT NULL,
    language_code character varying(10) NOT NULL,
    language_label character varying(100) NOT NULL,
    language_flag_base64 text,
    is_default boolean NOT NULL,
    core_translation json,
    domain_translation json
);


--
-- Name: registry_theme_values; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.registry_theme_values (
    theme_value_id character varying NOT NULL,
    theme_id character varying NOT NULL,
    attribute_name public.registry_theme_attribute_name_enum NOT NULL,
    attribute_value text NOT NULL
);


--
-- Name: registry_themes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.registry_themes (
    theme_id character varying NOT NULL,
    theme_mnemonic character varying(50) NOT NULL,
    is_factory_shipped boolean NOT NULL
);


--
-- Name: subscription_activity_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.subscription_activity_logs (
    subscription_activity_log_id character varying NOT NULL,
    is_unsubscribe boolean NOT NULL,
    description character varying,
    partner_id character varying NOT NULL,
    subscription_url character varying NOT NULL,
    registry_callback_url character varying NOT NULL,
    header json,
    payload json,
    response json,
    date_time timestamp without time zone NOT NULL
);


--
-- Name: awe_req_events awe_req_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.awe_req_events
    ADD CONSTRAINT awe_req_events_pkey PRIMARY KEY (event_id);


--
-- Name: data_models data_models_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_models
    ADD CONSTRAINT data_models_pkey PRIMARY KEY (data_model_id);


--
-- Name: dedup_results_intake_forms_vs_intake_forms dedup_results_intake_forms_vs_intake_forms_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dedup_results_intake_forms_vs_intake_forms
    ADD CONSTRAINT dedup_results_intake_forms_vs_intake_forms_pkey PRIMARY KEY (dedup_result_id);


--
-- Name: dedup_results_intake_forms_vs_register dedup_results_intake_forms_vs_register_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dedup_results_intake_forms_vs_register
    ADD CONSTRAINT dedup_results_intake_forms_vs_register_pkey PRIMARY KEY (dedup_result_id);


--
-- Name: deduplication_change_request_results deduplication_change_request_results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deduplication_change_request_results
    ADD CONSTRAINT deduplication_change_request_results_pkey PRIMARY KEY (dedup_result_id);


--
-- Name: deduplication_register_results deduplication_register_results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deduplication_register_results
    ADD CONSTRAINT deduplication_register_results_pkey PRIMARY KEY (dedup_result_id);


--
-- Name: dbt_change_request_documents dbt_change_request_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_change_request_documents
    ADD CONSTRAINT dbt_change_request_documents_pkey PRIMARY KEY (change_request_id, document_id);


--
-- Name: dbt_completion_score_computation_queue dbt_completion_score_computation_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_completion_score_computation_queue
    ADD CONSTRAINT dbt_completion_score_computation_queue_pkey PRIMARY KEY (queue_id);


--
-- Name: dbt_functional_id_generation_queue dbt_functional_id_generation_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_functional_id_generation_queue
    ADD CONSTRAINT dbt_functional_id_generation_queue_pkey PRIMARY KEY (queue_id);


--
-- Name: dbt_input_mechanisms dbt_input_mechanisms_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_input_mechanisms
    ADD CONSTRAINT dbt_input_mechanisms_pkey PRIMARY KEY (mechanism_id);


--
-- Name: dbt_intake_form_definitions dbt_intake_form_definitions_form_mnemonic_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_intake_form_definitions
    ADD CONSTRAINT dbt_intake_form_definitions_form_mnemonic_key UNIQUE (form_mnemonic);


--
-- Name: dbt_intake_form_definitions dbt_intake_form_definitions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_intake_form_definitions
    ADD CONSTRAINT dbt_intake_form_definitions_pkey PRIMARY KEY (form_id);


--
-- Name: dbt_intake_form_household_assets dbt_intake_form_household_assets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_intake_form_household_assets
    ADD CONSTRAINT dbt_intake_form_household_assets_pkey PRIMARY KEY (submission_id, internal_record_id);


--
-- Name: dbt_intake_form_household_housing_and_services dbt_intake_form_household_housing_and_services_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_intake_form_household_housing_and_services
    ADD CONSTRAINT dbt_intake_form_household_housing_and_services_pkey PRIMARY KEY (submission_id, internal_record_id);


--
-- Name: dbt_intake_form_household_programs dbt_intake_form_household_programs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_intake_form_household_programs
    ADD CONSTRAINT dbt_intake_form_household_programs_pkey PRIMARY KEY (submission_id, internal_record_id);


--
-- Name: dbt_intake_form_households dbt_intake_form_households_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_intake_form_households
    ADD CONSTRAINT dbt_intake_form_households_pkey PRIMARY KEY (submission_id, internal_record_id);


--
-- Name: dbt_intake_form_individual_disabilities dbt_intake_form_individual_disabilities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_intake_form_individual_disabilities
    ADD CONSTRAINT dbt_intake_form_individual_disabilities_pkey PRIMARY KEY (submission_id, internal_record_id);


--
-- Name: dbt_intake_form_individual_land dbt_intake_form_individual_land_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_intake_form_individual_land
    ADD CONSTRAINT dbt_intake_form_individual_land_pkey PRIMARY KEY (submission_id, internal_record_id);


--
-- Name: dbt_intake_form_individual_livelihoods dbt_intake_form_individual_livelihoods_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_intake_form_individual_livelihoods
    ADD CONSTRAINT dbt_intake_form_individual_livelihoods_pkey PRIMARY KEY (submission_id, internal_record_id);


--
-- Name: dbt_intake_form_individual_livestock dbt_intake_form_individual_livestock_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_intake_form_individual_livestock
    ADD CONSTRAINT dbt_intake_form_individual_livestock_pkey PRIMARY KEY (submission_id, internal_record_id);


--
-- Name: dbt_intake_form_individual_programs dbt_intake_form_individual_programs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_intake_form_individual_programs
    ADD CONSTRAINT dbt_intake_form_individual_programs_pkey PRIMARY KEY (submission_id, internal_record_id);


--
-- Name: dbt_intake_form_individual_shocks dbt_intake_form_individual_shocks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_intake_form_individual_shocks
    ADD CONSTRAINT dbt_intake_form_individual_shocks_pkey PRIMARY KEY (submission_id, internal_record_id);


--
-- Name: dbt_intake_form_individual_vulnerability dbt_intake_form_individual_vulnerability_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_intake_form_individual_vulnerability
    ADD CONSTRAINT dbt_intake_form_individual_vulnerability_pkey PRIMARY KEY (submission_id, internal_record_id);


--
-- Name: dbt_intake_form_individuals dbt_intake_form_individuals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_intake_form_individuals
    ADD CONSTRAINT dbt_intake_form_individuals_pkey PRIMARY KEY (submission_id, internal_record_id);


--
-- Name: dbt_intake_form_submissions dbt_intake_form_submissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_intake_form_submissions
    ADD CONSTRAINT dbt_intake_form_submissions_pkey PRIMARY KEY (submission_id);


--
-- Name: dbt_intake_form_ui_tab_sections dbt_intake_form_ui_tab_sections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_intake_form_ui_tab_sections
    ADD CONSTRAINT dbt_intake_form_ui_tab_sections_pkey PRIMARY KEY (tab_section_id);


--
-- Name: dbt_intake_form_ui_tabs dbt_intake_form_ui_tabs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_intake_form_ui_tabs
    ADD CONSTRAINT dbt_intake_form_ui_tabs_pkey PRIMARY KEY (tab_id);


--
-- Name: dbt_intake_section_documents dbt_intake_section_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_intake_section_documents
    ADD CONSTRAINT dbt_intake_section_documents_pkey PRIMARY KEY (submission_id, document_id);


--
-- Name: dbt_register_change_request_payloads dbt_register_change_request_payloads_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_change_request_payloads
    ADD CONSTRAINT dbt_register_change_request_payloads_pkey PRIMARY KEY (change_request_id);


--
-- Name: dbt_register_change_requests dbt_register_change_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_change_requests
    ADD CONSTRAINT dbt_register_change_requests_pkey PRIMARY KEY (change_request_id);


--
-- Name: dbt_register_definitions dbt_register_definitions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_definitions
    ADD CONSTRAINT dbt_register_definitions_pkey PRIMARY KEY (register_id);


--
-- Name: dbt_register_document_history dbt_register_document_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_document_history
    ADD CONSTRAINT dbt_register_document_history_pkey PRIMARY KEY (document_history_id);


--
-- Name: dbt_register_export_data_queue dbt_register_export_data_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_export_data_queue
    ADD CONSTRAINT dbt_register_export_data_queue_pkey PRIMARY KEY (export_id);


--
-- Name: dbt_register_history_household_assets dbt_register_history_household_assets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_history_household_assets
    ADD CONSTRAINT dbt_register_history_household_assets_pkey PRIMARY KEY (history_record_id);


--
-- Name: dbt_register_history_household_housing_and_services dbt_register_history_household_housing_and_services_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_history_household_housing_and_services
    ADD CONSTRAINT dbt_register_history_household_housing_and_services_pkey PRIMARY KEY (history_record_id);


--
-- Name: dbt_register_history_household_programs dbt_register_history_household_programs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_history_household_programs
    ADD CONSTRAINT dbt_register_history_household_programs_pkey PRIMARY KEY (history_record_id);


--
-- Name: dbt_register_history_households dbt_register_history_households_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_history_households
    ADD CONSTRAINT dbt_register_history_households_pkey PRIMARY KEY (history_record_id);


--
-- Name: dbt_register_history_individual_disabilities dbt_register_history_individual_disabilities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_history_individual_disabilities
    ADD CONSTRAINT dbt_register_history_individual_disabilities_pkey PRIMARY KEY (history_record_id);


--
-- Name: dbt_register_history_individual_land dbt_register_history_individual_land_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_history_individual_land
    ADD CONSTRAINT dbt_register_history_individual_land_pkey PRIMARY KEY (history_record_id);


--
-- Name: dbt_register_history_individual_livelihoods dbt_register_history_individual_livelihoods_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_history_individual_livelihoods
    ADD CONSTRAINT dbt_register_history_individual_livelihoods_pkey PRIMARY KEY (history_record_id);


--
-- Name: dbt_register_history_individual_livestock dbt_register_history_individual_livestock_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_history_individual_livestock
    ADD CONSTRAINT dbt_register_history_individual_livestock_pkey PRIMARY KEY (history_record_id);


--
-- Name: dbt_register_history_individual_programs dbt_register_history_individual_programs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_history_individual_programs
    ADD CONSTRAINT dbt_register_history_individual_programs_pkey PRIMARY KEY (history_record_id);


--
-- Name: dbt_register_history_individual_shocks dbt_register_history_individual_shocks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_history_individual_shocks
    ADD CONSTRAINT dbt_register_history_individual_shocks_pkey PRIMARY KEY (history_record_id);


--
-- Name: dbt_register_history_individual_vulnerability dbt_register_history_individual_vulnerability_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_history_individual_vulnerability
    ADD CONSTRAINT dbt_register_history_individual_vulnerability_pkey PRIMARY KEY (history_record_id);


--
-- Name: dbt_register_history_individuals dbt_register_history_individuals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_history_individuals
    ADD CONSTRAINT dbt_register_history_individuals_pkey PRIMARY KEY (history_record_id);


--
-- Name: dbt_register_household_assets dbt_register_household_assets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_household_assets
    ADD CONSTRAINT dbt_register_household_assets_pkey PRIMARY KEY (internal_record_id);


--
-- Name: dbt_register_household_housing_and_services dbt_register_household_housing_and_services_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_household_housing_and_services
    ADD CONSTRAINT dbt_register_household_housing_and_services_pkey PRIMARY KEY (internal_record_id);


--
-- Name: dbt_register_household_programs dbt_register_household_programs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_household_programs
    ADD CONSTRAINT dbt_register_household_programs_pkey PRIMARY KEY (internal_record_id);


--
-- Name: dbt_register_households dbt_register_households_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_households
    ADD CONSTRAINT dbt_register_households_pkey PRIMARY KEY (internal_record_id);


--
-- Name: dbt_register_individual_disabilities dbt_register_individual_disabilities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_individual_disabilities
    ADD CONSTRAINT dbt_register_individual_disabilities_pkey PRIMARY KEY (internal_record_id);


--
-- Name: dbt_register_individual_land dbt_register_individual_land_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_individual_land
    ADD CONSTRAINT dbt_register_individual_land_pkey PRIMARY KEY (internal_record_id);


--
-- Name: dbt_register_individual_livelihoods dbt_register_individual_livelihoods_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_individual_livelihoods
    ADD CONSTRAINT dbt_register_individual_livelihoods_pkey PRIMARY KEY (internal_record_id);


--
-- Name: dbt_register_individual_livestock dbt_register_individual_livestock_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_individual_livestock
    ADD CONSTRAINT dbt_register_individual_livestock_pkey PRIMARY KEY (internal_record_id);


--
-- Name: dbt_register_individual_programs dbt_register_individual_programs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_individual_programs
    ADD CONSTRAINT dbt_register_individual_programs_pkey PRIMARY KEY (internal_record_id);


--
-- Name: dbt_register_individual_shocks dbt_register_individual_shocks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_individual_shocks
    ADD CONSTRAINT dbt_register_individual_shocks_pkey PRIMARY KEY (internal_record_id);


--
-- Name: dbt_register_individual_vulnerability dbt_register_individual_vulnerability_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_individual_vulnerability
    ADD CONSTRAINT dbt_register_individual_vulnerability_pkey PRIMARY KEY (internal_record_id);


--
-- Name: dbt_register_individuals dbt_register_individuals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_individuals
    ADD CONSTRAINT dbt_register_individuals_pkey PRIMARY KEY (internal_record_id);


--
-- Name: dbt_register_schemas dbt_register_schemas_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_schemas
    ADD CONSTRAINT dbt_register_schemas_pkey PRIMARY KEY (register_id);


--
-- Name: dbt_register_score_contributing_attributes dbt_register_score_contributing_attributes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_score_contributing_attributes
    ADD CONSTRAINT dbt_register_score_contributing_attributes_pkey PRIMARY KEY (contributing_attribute_id);


--
-- Name: dbt_register_score_definitions dbt_register_score_definitions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_score_definitions
    ADD CONSTRAINT dbt_register_score_definitions_pkey PRIMARY KEY (score_definition_id);


--
-- Name: dbt_register_score_history dbt_register_score_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_score_history
    ADD CONSTRAINT dbt_register_score_history_pkey PRIMARY KEY (internal_record_id);


--
-- Name: dbt_register_scores dbt_register_scores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_scores
    ADD CONSTRAINT dbt_register_scores_pkey PRIMARY KEY (internal_record_id);


--
-- Name: dbt_register_section_completion_score dbt_register_section_completion_score_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_section_completion_score
    ADD CONSTRAINT dbt_register_section_completion_score_pkey PRIMARY KEY (id);


--
-- Name: dbt_register_section_documents dbt_register_section_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_section_documents
    ADD CONSTRAINT dbt_register_section_documents_pkey PRIMARY KEY (internal_record_id, document_id);


--
-- Name: dbt_register_sections dbt_register_sections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_sections
    ADD CONSTRAINT dbt_register_sections_pkey PRIMARY KEY (section_id);


--
-- Name: dbt_register_ui_tab_sections dbt_register_ui_tab_sections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_ui_tab_sections
    ADD CONSTRAINT dbt_register_ui_tab_sections_pkey PRIMARY KEY (tab_section_id);


--
-- Name: dbt_register_ui_tabs dbt_register_ui_tabs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_ui_tabs
    ADD CONSTRAINT dbt_register_ui_tabs_pkey PRIMARY KEY (tab_id);


--
-- Name: dbt_register_verifications dbt_register_verifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_verifications
    ADD CONSTRAINT dbt_register_verifications_pkey PRIMARY KEY (verification_id);


--
-- Name: dbt_registrant_authentication_providers dbt_registrant_authentication_providers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_registrant_authentication_providers
    ADD CONSTRAINT dbt_registrant_authentication_providers_pkey PRIMARY KEY (provider_id);


--
-- Name: dbt_registrant_authentications dbt_registrant_authentications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_registrant_authentications
    ADD CONSTRAINT dbt_registrant_authentications_pkey PRIMARY KEY (authentication_id);


--
-- Name: dbt_registry_awe_policy_configurations dbt_registry_awe_policy_configurations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_registry_awe_policy_configurations
    ADD CONSTRAINT dbt_registry_awe_policy_configurations_pkey PRIMARY KEY (awe_policy_config_id);


--
-- Name: dbt_registry_configuration dbt_registry_configuration_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_registry_configuration
    ADD CONSTRAINT dbt_registry_configuration_pkey PRIMARY KEY (configuration_id);


--
-- Name: dbt_registry_data_policies dbt_registry_data_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_registry_data_policies
    ADD CONSTRAINT dbt_registry_data_policies_pkey PRIMARY KEY (policy_id);


--
-- Name: dbt_registry_documents dbt_registry_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_registry_documents
    ADD CONSTRAINT dbt_registry_documents_pkey PRIMARY KEY (document_id);


--
-- Name: dbt_registry_import_file_configurations dbt_registry_import_file_configurations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_registry_import_file_configurations
    ADD CONSTRAINT dbt_registry_import_file_configurations_pkey PRIMARY KEY (import_file_configuration_id);


--
-- Name: dbt_registry_vc_configurations dbt_registry_vc_configurations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_registry_vc_configurations
    ADD CONSTRAINT dbt_registry_vc_configurations_pkey PRIMARY KEY (vc_config_id);


--
-- Name: dbt_score_compute_queue dbt_score_compute_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_score_compute_queue
    ADD CONSTRAINT dbt_score_compute_queue_pkey PRIMARY KEY (queue_id);


--
-- Name: import_file_process_log import_file_process_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_file_process_log
    ADD CONSTRAINT import_file_process_log_pkey PRIMARY KEY (import_file_record_id);


--
-- Name: import_file_process_queue import_file_process_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_file_process_queue
    ADD CONSTRAINT import_file_process_queue_pkey PRIMARY KEY (import_file_id);


--
-- Name: incoming_classified_data incoming_classified_data_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incoming_classified_data
    ADD CONSTRAINT incoming_classified_data_pkey PRIMARY KEY (ingest_id);


--
-- Name: incoming_enriched_transformed_data incoming_enriched_transformed_data_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incoming_enriched_transformed_data
    ADD CONSTRAINT incoming_enriched_transformed_data_pkey PRIMARY KEY (ingest_id);


--
-- Name: incoming_model_key_paths incoming_model_key_paths_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incoming_model_key_paths
    ADD CONSTRAINT incoming_model_key_paths_pkey PRIMARY KEY (key_path_id);


--
-- Name: incoming_model_register_semantic_patterns incoming_model_register_semantic_patterns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incoming_model_register_semantic_patterns
    ADD CONSTRAINT incoming_model_register_semantic_patterns_pkey PRIMARY KEY (register_semantic_pattern_id);


--
-- Name: incoming_model_semantic_patterns incoming_model_semantic_patterns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incoming_model_semantic_patterns
    ADD CONSTRAINT incoming_model_semantic_patterns_pkey PRIMARY KEY (semantic_pattern_id);


--
-- Name: incoming_raw_data_payloads incoming_raw_data_payloads_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incoming_raw_data_payloads
    ADD CONSTRAINT incoming_raw_data_payloads_pkey PRIMARY KEY (ingest_id);


--
-- Name: incoming_raw_data incoming_raw_data_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incoming_raw_data
    ADD CONSTRAINT incoming_raw_data_pkey PRIMARY KEY (ingest_id);


--
-- Name: incoming_templates incoming_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incoming_templates
    ADD CONSTRAINT incoming_templates_pkey PRIMARY KEY (template_id);


--
-- Name: ndbt_geography_areas ndbt_geography_areas_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ndbt_geography_areas
    ADD CONSTRAINT ndbt_geography_areas_pkey PRIMARY KEY (area_id);


--
-- Name: outgoing_raw_data_payloads outgoing_raw_data_payloads_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outgoing_raw_data_payloads
    ADD CONSTRAINT outgoing_raw_data_payloads_pkey PRIMARY KEY (payload_id);


--
-- Name: outgoing_raw_data outgoing_raw_data_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outgoing_raw_data
    ADD CONSTRAINT outgoing_raw_data_pkey PRIMARY KEY (outgest_id);


--
-- Name: outgoing_templates outgoing_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outgoing_templates
    ADD CONSTRAINT outgoing_templates_pkey PRIMARY KEY (template_id);


--
-- Name: outgoing_topics outgoing_topics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outgoing_topics
    ADD CONSTRAINT outgoing_topics_pkey PRIMARY KEY (topic_id);


--
-- Name: outgoing_transformed_data_payloads outgoing_transformed_data_payloads_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outgoing_transformed_data_payloads
    ADD CONSTRAINT outgoing_transformed_data_payloads_pkey PRIMARY KEY (outgest_id);


--
-- Name: registry_languages registry_languages_language_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.registry_languages
    ADD CONSTRAINT registry_languages_language_code_key UNIQUE (language_code);


--
-- Name: registry_languages registry_languages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.registry_languages
    ADD CONSTRAINT registry_languages_pkey PRIMARY KEY (language_id);


--
-- Name: registry_theme_values registry_theme_values_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.registry_theme_values
    ADD CONSTRAINT registry_theme_values_pkey PRIMARY KEY (theme_value_id);


--
-- Name: registry_themes registry_themes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.registry_themes
    ADD CONSTRAINT registry_themes_pkey PRIMARY KEY (theme_id);


--
-- Name: registry_themes registry_themes_theme_mnemonic_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.registry_themes
    ADD CONSTRAINT registry_themes_theme_mnemonic_key UNIQUE (theme_mnemonic);


--
-- Name: subscription_activity_logs subscription_activity_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscription_activity_logs
    ADD CONSTRAINT subscription_activity_logs_pkey PRIMARY KEY (subscription_activity_log_id);


--
-- Name: outgoing_templates uix_dr_outgoing_templates; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outgoing_templates
    ADD CONSTRAINT uix_dr_outgoing_templates UNIQUE (data_model_id, register_id);


--
-- Name: outgoing_topics uix_dr_outgoing_topics; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outgoing_topics
    ADD CONSTRAINT uix_dr_outgoing_topics UNIQUE (data_model_id, register_id);


--
-- Name: incoming_templates uix_dro_2; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incoming_templates
    ADD CONSTRAINT uix_dro_2 UNIQUE (data_model_id, register_id);


--
-- Name: dbt_register_section_completion_score uq_section_completion_score; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbt_register_section_completion_score
    ADD CONSTRAINT uq_section_completion_score UNIQUE (register_id, internal_record_id, section_id);


--
-- Name: idx_dedup_change_request_candidate_change_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dedup_change_request_candidate_change_request_id ON public.deduplication_change_request_results USING btree (candidate_change_request_id);


--
-- Name: idx_dedup_change_request_change_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dedup_change_request_change_request_id ON public.deduplication_change_request_results USING btree (change_request_id);


--
-- Name: idx_dedup_if_if_candidate_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dedup_if_if_candidate_submission_id ON public.dedup_results_intake_forms_vs_intake_forms USING btree (candidate_submission_id);


--
-- Name: idx_dedup_if_if_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dedup_if_if_submission_id ON public.dedup_results_intake_forms_vs_intake_forms USING btree (submission_id);


--
-- Name: idx_dedup_if_register_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dedup_if_register_internal_record_id ON public.dedup_results_intake_forms_vs_register USING btree (internal_record_id);


--
-- Name: idx_dedup_if_register_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dedup_if_register_submission_id ON public.dedup_results_intake_forms_vs_register USING btree (submission_id);


--
-- Name: idx_dedup_register_change_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dedup_register_change_request_id ON public.deduplication_register_results USING btree (change_request_id);


--
-- Name: idx_dedup_register_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dedup_register_internal_record_id ON public.deduplication_register_results USING btree (internal_record_id);


--
-- Name: idx_registrant_auth_expiry_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_registrant_auth_expiry_at ON public.dbt_registrant_authentications USING btree (expiry_at);


--
-- Name: idx_registrant_auth_internal_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_registrant_auth_internal_status ON public.dbt_registrant_authentications USING btree (internal_record_id, status);


--
-- Name: idx_registrant_auth_register_internal; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_registrant_auth_register_internal ON public.dbt_registrant_authentications USING btree (register_id, internal_record_id);


--
-- Name: ix_awe_req_events_artifact_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_awe_req_events_artifact_id ON public.awe_req_events USING btree (artifact_id);


--
-- Name: ix_awe_req_events_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_awe_req_events_event_type ON public.awe_req_events USING btree (event_type);


--
-- Name: ix_awe_req_events_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_awe_req_events_request_id ON public.awe_req_events USING btree (request_id);


--
-- Name: ix_data_models_data_model_mnemonic; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_data_models_data_model_mnemonic ON public.data_models USING btree (data_model_mnemonic);


--
-- Name: ix_dedup_results_intake_forms_vs_intake_forms_candidate_257c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dedup_results_intake_forms_vs_intake_forms_candidate_257c ON public.dedup_results_intake_forms_vs_intake_forms USING btree (candidate_submission_id);


--
-- Name: ix_dedup_results_intake_forms_vs_intake_forms_section_r_30ea; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dedup_results_intake_forms_vs_intake_forms_section_r_30ea ON public.dedup_results_intake_forms_vs_intake_forms USING btree (section_register_id);


--
-- Name: ix_dedup_results_intake_forms_vs_intake_forms_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dedup_results_intake_forms_vs_intake_forms_submission_id ON public.dedup_results_intake_forms_vs_intake_forms USING btree (submission_id);


--
-- Name: ix_dedup_results_intake_forms_vs_register_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dedup_results_intake_forms_vs_register_internal_record_id ON public.dedup_results_intake_forms_vs_register USING btree (internal_record_id);


--
-- Name: ix_dedup_results_intake_forms_vs_register_section_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dedup_results_intake_forms_vs_register_section_register_id ON public.dedup_results_intake_forms_vs_register USING btree (section_register_id);


--
-- Name: ix_dedup_results_intake_forms_vs_register_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dedup_results_intake_forms_vs_register_submission_id ON public.dedup_results_intake_forms_vs_register USING btree (submission_id);


--
-- Name: ix_deduplication_change_request_results_candidate_chang_7e2d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_deduplication_change_request_results_candidate_chang_7e2d ON public.deduplication_change_request_results USING btree (candidate_change_request_id);


--
-- Name: ix_deduplication_change_request_results_change_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_deduplication_change_request_results_change_request_id ON public.deduplication_change_request_results USING btree (change_request_id);


--
-- Name: ix_deduplication_register_results_change_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_deduplication_register_results_change_request_id ON public.deduplication_register_results USING btree (change_request_id);


--
-- Name: ix_deduplication_register_results_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_deduplication_register_results_internal_record_id ON public.deduplication_register_results USING btree (internal_record_id);


--
-- Name: ix_dbt_change_request_documents_change_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_change_request_documents_change_request_id ON public.dbt_change_request_documents USING btree (change_request_id);


--
-- Name: ix_dbt_change_request_documents_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_change_request_documents_document_id ON public.dbt_change_request_documents USING btree (document_id);


--
-- Name: ix_dbt_change_request_documents_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_change_request_documents_section_id ON public.dbt_change_request_documents USING btree (section_id);


--
-- Name: ix_dbt_completion_score_computation_queue_change_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_completion_score_computation_queue_change_request_id ON public.dbt_completion_score_computation_queue USING btree (change_request_id);


--
-- Name: ix_dbt_completion_score_computation_queue_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_completion_score_computation_queue_internal_record_id ON public.dbt_completion_score_computation_queue USING btree (internal_record_id);


--
-- Name: ix_dbt_completion_score_computation_queue_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_completion_score_computation_queue_register_id ON public.dbt_completion_score_computation_queue USING btree (register_id);


--
-- Name: ix_dbt_completion_score_computation_queue_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_completion_score_computation_queue_section_id ON public.dbt_completion_score_computation_queue USING btree (section_id);


--
-- Name: ix_dbt_completion_score_computation_queue_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_completion_score_computation_queue_submission_id ON public.dbt_completion_score_computation_queue USING btree (submission_id);


--
-- Name: ix_dbt_functional_id_generation_queue_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_functional_id_generation_queue_internal_record_id ON public.dbt_functional_id_generation_queue USING btree (internal_record_id);


--
-- Name: ix_dbt_functional_id_generation_queue_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_functional_id_generation_queue_register_id ON public.dbt_functional_id_generation_queue USING btree (register_id);


--
-- Name: ix_dbt_intake_form_definitions_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_definitions_register_id ON public.dbt_intake_form_definitions USING btree (register_id);


--
-- Name: ix_dbt_intake_form_household_assets_application_reference; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_household_assets_application_reference ON public.dbt_intake_form_household_assets USING btree (application_reference);


--
-- Name: ix_dbt_intake_form_household_assets_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_intake_form_household_assets_functional_record_id ON public.dbt_intake_form_household_assets USING btree (functional_record_id);


--
-- Name: ix_dbt_intake_form_household_assets_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_household_assets_link_foundational_id ON public.dbt_intake_form_household_assets USING btree (link_foundational_id);


--
-- Name: ix_dbt_intake_form_household_assets_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_household_assets_link_internal_record_id ON public.dbt_intake_form_household_assets USING btree (link_internal_record_id);


--
-- Name: ix_dbt_intake_form_household_housing_and_services_appli_e819; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_household_housing_and_services_appli_e819 ON public.dbt_intake_form_household_housing_and_services USING btree (application_reference);


--
-- Name: ix_dbt_intake_form_household_housing_and_services_funct_cf08; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_intake_form_household_housing_and_services_funct_cf08 ON public.dbt_intake_form_household_housing_and_services USING btree (functional_record_id);


--
-- Name: ix_dbt_intake_form_household_housing_and_services_link__681d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_household_housing_and_services_link__681d ON public.dbt_intake_form_household_housing_and_services USING btree (link_foundational_id);


--
-- Name: ix_dbt_intake_form_household_housing_and_services_link__7116; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_household_housing_and_services_link__7116 ON public.dbt_intake_form_household_housing_and_services USING btree (link_internal_record_id);


--
-- Name: ix_dbt_intake_form_household_programs_application_reference; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_household_programs_application_reference ON public.dbt_intake_form_household_programs USING btree (application_reference);


--
-- Name: ix_dbt_intake_form_household_programs_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_intake_form_household_programs_functional_record_id ON public.dbt_intake_form_household_programs USING btree (functional_record_id);


--
-- Name: ix_dbt_intake_form_household_programs_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_household_programs_link_foundational_id ON public.dbt_intake_form_household_programs USING btree (link_foundational_id);


--
-- Name: ix_dbt_intake_form_household_programs_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_household_programs_link_internal_record_id ON public.dbt_intake_form_household_programs USING btree (link_internal_record_id);


--
-- Name: ix_dbt_intake_form_households_application_reference; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_households_application_reference ON public.dbt_intake_form_households USING btree (application_reference);


--
-- Name: ix_dbt_intake_form_households_country_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_households_country_code ON public.dbt_intake_form_households USING btree (country_code);


--
-- Name: ix_dbt_intake_form_households_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_intake_form_households_functional_record_id ON public.dbt_intake_form_households USING btree (functional_record_id);


--
-- Name: ix_dbt_intake_form_households_geo_lowest_level_value_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_households_geo_lowest_level_value_id ON public.dbt_intake_form_households USING btree (geo_lowest_level_value_id);


--
-- Name: ix_dbt_intake_form_households_household_head_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_households_household_head_internal_record_id ON public.dbt_intake_form_households USING btree (household_head_internal_record_id);


--
-- Name: ix_dbt_intake_form_households_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_households_link_foundational_id ON public.dbt_intake_form_households USING btree (link_foundational_id);


--
-- Name: ix_dbt_intake_form_households_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_households_link_internal_record_id ON public.dbt_intake_form_households USING btree (link_internal_record_id);


--
-- Name: ix_dbt_intake_form_households_plus_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_households_plus_code ON public.dbt_intake_form_households USING btree (plus_code);


--
-- Name: ix_dbt_intake_form_households_postal_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_households_postal_code ON public.dbt_intake_form_households USING btree (postal_code);


--
-- Name: ix_dbt_intake_form_individual_disabilities_application__8489; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_disabilities_application__8489 ON public.dbt_intake_form_individual_disabilities USING btree (application_reference);


--
-- Name: ix_dbt_intake_form_individual_disabilities_disability_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_disabilities_disability_domain ON public.dbt_intake_form_individual_disabilities USING btree (disability_domain);


--
-- Name: ix_dbt_intake_form_individual_disabilities_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_intake_form_individual_disabilities_functional_record_id ON public.dbt_intake_form_individual_disabilities USING btree (functional_record_id);


--
-- Name: ix_dbt_intake_form_individual_disabilities_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_disabilities_link_foundational_id ON public.dbt_intake_form_individual_disabilities USING btree (link_foundational_id);


--
-- Name: ix_dbt_intake_form_individual_disabilities_link_interna_82d7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_disabilities_link_interna_82d7 ON public.dbt_intake_form_individual_disabilities USING btree (link_internal_record_id);


--
-- Name: ix_dbt_intake_form_individual_land_application_reference; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_land_application_reference ON public.dbt_intake_form_individual_land USING btree (application_reference);


--
-- Name: ix_dbt_intake_form_individual_land_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_intake_form_individual_land_functional_record_id ON public.dbt_intake_form_individual_land USING btree (functional_record_id);


--
-- Name: ix_dbt_intake_form_individual_land_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_land_link_foundational_id ON public.dbt_intake_form_individual_land USING btree (link_foundational_id);


--
-- Name: ix_dbt_intake_form_individual_land_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_land_link_internal_record_id ON public.dbt_intake_form_individual_land USING btree (link_internal_record_id);


--
-- Name: ix_dbt_intake_form_individual_livelihoods_application_reference; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_livelihoods_application_reference ON public.dbt_intake_form_individual_livelihoods USING btree (application_reference);


--
-- Name: ix_dbt_intake_form_individual_livelihoods_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_intake_form_individual_livelihoods_functional_record_id ON public.dbt_intake_form_individual_livelihoods USING btree (functional_record_id);


--
-- Name: ix_dbt_intake_form_individual_livelihoods_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_livelihoods_link_foundational_id ON public.dbt_intake_form_individual_livelihoods USING btree (link_foundational_id);


--
-- Name: ix_dbt_intake_form_individual_livelihoods_link_internal_676f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_livelihoods_link_internal_676f ON public.dbt_intake_form_individual_livelihoods USING btree (link_internal_record_id);


--
-- Name: ix_dbt_intake_form_individual_livestock_application_reference; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_livestock_application_reference ON public.dbt_intake_form_individual_livestock USING btree (application_reference);


--
-- Name: ix_dbt_intake_form_individual_livestock_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_intake_form_individual_livestock_functional_record_id ON public.dbt_intake_form_individual_livestock USING btree (functional_record_id);


--
-- Name: ix_dbt_intake_form_individual_livestock_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_livestock_link_foundational_id ON public.dbt_intake_form_individual_livestock USING btree (link_foundational_id);


--
-- Name: ix_dbt_intake_form_individual_livestock_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_livestock_link_internal_record_id ON public.dbt_intake_form_individual_livestock USING btree (link_internal_record_id);


--
-- Name: ix_dbt_intake_form_individual_programs_application_reference; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_programs_application_reference ON public.dbt_intake_form_individual_programs USING btree (application_reference);


--
-- Name: ix_dbt_intake_form_individual_programs_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_intake_form_individual_programs_functional_record_id ON public.dbt_intake_form_individual_programs USING btree (functional_record_id);


--
-- Name: ix_dbt_intake_form_individual_programs_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_programs_link_foundational_id ON public.dbt_intake_form_individual_programs USING btree (link_foundational_id);


--
-- Name: ix_dbt_intake_form_individual_programs_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_programs_link_internal_record_id ON public.dbt_intake_form_individual_programs USING btree (link_internal_record_id);


--
-- Name: ix_dbt_intake_form_individual_shocks_application_reference; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_shocks_application_reference ON public.dbt_intake_form_individual_shocks USING btree (application_reference);


--
-- Name: ix_dbt_intake_form_individual_shocks_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_intake_form_individual_shocks_functional_record_id ON public.dbt_intake_form_individual_shocks USING btree (functional_record_id);


--
-- Name: ix_dbt_intake_form_individual_shocks_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_shocks_link_foundational_id ON public.dbt_intake_form_individual_shocks USING btree (link_foundational_id);


--
-- Name: ix_dbt_intake_form_individual_shocks_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_shocks_link_internal_record_id ON public.dbt_intake_form_individual_shocks USING btree (link_internal_record_id);


--
-- Name: ix_dbt_intake_form_individual_shocks_shock_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_shocks_shock_date ON public.dbt_intake_form_individual_shocks USING btree (shock_date);


--
-- Name: ix_dbt_intake_form_individual_vulnerability_application_e0e5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_vulnerability_application_e0e5 ON public.dbt_intake_form_individual_vulnerability USING btree (application_reference);


--
-- Name: ix_dbt_intake_form_individual_vulnerability_functional__dbd2; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_intake_form_individual_vulnerability_functional__dbd2 ON public.dbt_intake_form_individual_vulnerability USING btree (functional_record_id);


--
-- Name: ix_dbt_intake_form_individual_vulnerability_link_founda_17c3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_vulnerability_link_founda_17c3 ON public.dbt_intake_form_individual_vulnerability USING btree (link_foundational_id);


--
-- Name: ix_dbt_intake_form_individual_vulnerability_link_intern_c958; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individual_vulnerability_link_intern_c958 ON public.dbt_intake_form_individual_vulnerability USING btree (link_internal_record_id);


--
-- Name: ix_dbt_intake_form_individuals_application_reference; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individuals_application_reference ON public.dbt_intake_form_individuals USING btree (application_reference);


--
-- Name: ix_dbt_intake_form_individuals_country_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individuals_country_code ON public.dbt_intake_form_individuals USING btree (country_code);


--
-- Name: ix_dbt_intake_form_individuals_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individuals_foundational_id ON public.dbt_intake_form_individuals USING btree (foundational_id);


--
-- Name: ix_dbt_intake_form_individuals_full_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individuals_full_name ON public.dbt_intake_form_individuals USING btree (full_name);


--
-- Name: ix_dbt_intake_form_individuals_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_intake_form_individuals_functional_record_id ON public.dbt_intake_form_individuals USING btree (functional_record_id);


--
-- Name: ix_dbt_intake_form_individuals_geo_lowest_level_value_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individuals_geo_lowest_level_value_id ON public.dbt_intake_form_individuals USING btree (geo_lowest_level_value_id);


--
-- Name: ix_dbt_intake_form_individuals_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individuals_link_foundational_id ON public.dbt_intake_form_individuals USING btree (link_foundational_id);


--
-- Name: ix_dbt_intake_form_individuals_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individuals_link_internal_record_id ON public.dbt_intake_form_individuals USING btree (link_internal_record_id);


--
-- Name: ix_dbt_intake_form_individuals_plus_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individuals_plus_code ON public.dbt_intake_form_individuals USING btree (plus_code);


--
-- Name: ix_dbt_intake_form_individuals_postal_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_individuals_postal_code ON public.dbt_intake_form_individuals USING btree (postal_code);


--
-- Name: ix_dbt_intake_form_submissions_application_reference; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_intake_form_submissions_application_reference ON public.dbt_intake_form_submissions USING btree (application_reference);


--
-- Name: ix_dbt_intake_form_submissions_awe_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_submissions_awe_request_id ON public.dbt_intake_form_submissions USING btree (awe_request_id);


--
-- Name: ix_dbt_intake_form_submissions_deduplication_status_vs__2127; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_submissions_deduplication_status_vs__2127 ON public.dbt_intake_form_submissions USING btree (deduplication_status_vs_intake_forms);


--
-- Name: ix_dbt_intake_form_submissions_deduplication_status_vs_register; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_submissions_deduplication_status_vs_register ON public.dbt_intake_form_submissions USING btree (deduplication_status_vs_register);


--
-- Name: ix_dbt_intake_form_submissions_form_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_submissions_form_id ON public.dbt_intake_form_submissions USING btree (form_id);


--
-- Name: ix_dbt_intake_form_submissions_partner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_submissions_partner_id ON public.dbt_intake_form_submissions USING btree (partner_id);


--
-- Name: ix_dbt_intake_form_submissions_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_submissions_register_id ON public.dbt_intake_form_submissions USING btree (register_id);


--
-- Name: ix_dbt_intake_form_ui_tab_sections_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_ui_tab_sections_section_id ON public.dbt_intake_form_ui_tab_sections USING btree (section_id);


--
-- Name: ix_dbt_intake_form_ui_tab_sections_tab_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_ui_tab_sections_tab_id ON public.dbt_intake_form_ui_tab_sections USING btree (tab_id);


--
-- Name: ix_dbt_intake_form_ui_tabs_form_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_form_ui_tabs_form_id ON public.dbt_intake_form_ui_tabs USING btree (form_id);


--
-- Name: ix_dbt_intake_section_documents_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_section_documents_document_id ON public.dbt_intake_section_documents USING btree (document_id);


--
-- Name: ix_dbt_intake_section_documents_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_section_documents_section_id ON public.dbt_intake_section_documents USING btree (section_id);


--
-- Name: ix_dbt_intake_section_documents_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_intake_section_documents_submission_id ON public.dbt_intake_section_documents USING btree (submission_id);


--
-- Name: ix_dbt_reg_score_contrib_reg_mnem_score_attr_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_reg_score_contrib_reg_mnem_score_attr_unique ON public.dbt_register_score_contributing_attributes USING btree (register_mnemonic, score_type, attribute_name);


--
-- Name: ix_dbt_register_change_request_payloads_search_text_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_change_request_payloads_search_text_gin ON public.dbt_register_change_request_payloads USING gin (search_text public.gin_trgm_ops);


--
-- Name: ix_dbt_register_change_requests_awe_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_change_requests_awe_request_id ON public.dbt_register_change_requests USING btree (awe_request_id);


--
-- Name: ix_dbt_register_change_requests_deduplication_change_re_d54f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_change_requests_deduplication_change_re_d54f ON public.dbt_register_change_requests USING btree (deduplication_change_request_status);


--
-- Name: ix_dbt_register_change_requests_deduplication_register_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_change_requests_deduplication_register_status ON public.dbt_register_change_requests USING btree (deduplication_register_status);


--
-- Name: ix_dbt_register_change_requests_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_change_requests_internal_record_id ON public.dbt_register_change_requests USING btree (internal_record_id);


--
-- Name: ix_dbt_register_change_requests_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_change_requests_register_id ON public.dbt_register_change_requests USING btree (register_id);


--
-- Name: ix_dbt_register_change_requests_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_change_requests_section_id ON public.dbt_register_change_requests USING btree (section_id);


--
-- Name: ix_dbt_register_change_requests_section_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_change_requests_section_register_id ON public.dbt_register_change_requests USING btree (section_register_id);


--
-- Name: ix_dbt_register_change_requests_source_partner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_change_requests_source_partner_id ON public.dbt_register_change_requests USING btree (source_partner_id);


--
-- Name: ix_dbt_register_change_requests_tab_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_change_requests_tab_id ON public.dbt_register_change_requests USING btree (tab_id);


--
-- Name: ix_dbt_register_definitions_master_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_definitions_master_register_id ON public.dbt_register_definitions USING btree (master_register_id);


--
-- Name: ix_dbt_register_definitions_program_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_definitions_program_id ON public.dbt_register_definitions USING btree (program_id);


--
-- Name: ix_dbt_register_definitions_program_mnemonic; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_definitions_program_mnemonic ON public.dbt_register_definitions USING btree (program_mnemonic);


--
-- Name: ix_dbt_register_definitions_register_mnemonic; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_register_definitions_register_mnemonic ON public.dbt_register_definitions USING btree (register_mnemonic);


--
-- Name: ix_dbt_register_document_history_change_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_document_history_change_request_id ON public.dbt_register_document_history USING btree (change_request_id);


--
-- Name: ix_dbt_register_document_history_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_document_history_document_id ON public.dbt_register_document_history USING btree (document_id);


--
-- Name: ix_dbt_register_document_history_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_document_history_internal_record_id ON public.dbt_register_document_history USING btree (internal_record_id);


--
-- Name: ix_dbt_register_document_history_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_document_history_section_id ON public.dbt_register_document_history USING btree (section_id);


--
-- Name: ix_dbt_register_document_history_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_document_history_submission_id ON public.dbt_register_document_history USING btree (submission_id);


--
-- Name: ix_dbt_register_export_data_queue_export_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_export_data_queue_export_status ON public.dbt_register_export_data_queue USING btree (export_status);


--
-- Name: ix_dbt_register_export_data_queue_queued_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_export_data_queue_queued_at ON public.dbt_register_export_data_queue USING btree (queued_at);


--
-- Name: ix_dbt_register_export_data_queue_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_export_data_queue_register_id ON public.dbt_register_export_data_queue USING btree (register_id);


--
-- Name: ix_dbt_register_export_data_queue_requested_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_export_data_queue_requested_by ON public.dbt_register_export_data_queue USING btree (requested_by);


--
-- Name: ix_dbt_register_history_household_assets_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_assets_functional_record_id ON public.dbt_register_history_household_assets USING btree (functional_record_id);


--
-- Name: ix_dbt_register_history_household_assets_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_assets_internal_record_id ON public.dbt_register_history_household_assets USING btree (internal_record_id);


--
-- Name: ix_dbt_register_history_household_assets_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_assets_link_foundational_id ON public.dbt_register_history_household_assets USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_history_household_assets_link_internal__d5dc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_assets_link_internal__d5dc ON public.dbt_register_history_household_assets USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_history_household_assets_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_assets_section_id ON public.dbt_register_history_household_assets USING btree (section_id);


--
-- Name: ix_dbt_register_history_household_assets_subject_intern_48c9; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_assets_subject_intern_48c9 ON public.dbt_register_history_household_assets USING btree (subject_internal_record_id);


--
-- Name: ix_dbt_register_history_household_assets_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_assets_submission_id ON public.dbt_register_history_household_assets USING btree (submission_id);


--
-- Name: ix_dbt_register_history_household_assets_tab_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_assets_tab_id ON public.dbt_register_history_household_assets USING btree (tab_id);


--
-- Name: ix_dbt_register_history_household_housing_and_services__0bab; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_housing_and_services__0bab ON public.dbt_register_history_household_housing_and_services USING btree (internal_record_id);


--
-- Name: ix_dbt_register_history_household_housing_and_services__0d67; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_housing_and_services__0d67 ON public.dbt_register_history_household_housing_and_services USING btree (subject_internal_record_id);


--
-- Name: ix_dbt_register_history_household_housing_and_services__4dbe; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_housing_and_services__4dbe ON public.dbt_register_history_household_housing_and_services USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_history_household_housing_and_services__5e00; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_housing_and_services__5e00 ON public.dbt_register_history_household_housing_and_services USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_history_household_housing_and_services__7de5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_housing_and_services__7de5 ON public.dbt_register_history_household_housing_and_services USING btree (submission_id);


--
-- Name: ix_dbt_register_history_household_housing_and_services__a840; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_housing_and_services__a840 ON public.dbt_register_history_household_housing_and_services USING btree (functional_record_id);


--
-- Name: ix_dbt_register_history_household_housing_and_services__e122; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_housing_and_services__e122 ON public.dbt_register_history_household_housing_and_services USING btree (section_id);


--
-- Name: ix_dbt_register_history_household_housing_and_services_tab_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_housing_and_services_tab_id ON public.dbt_register_history_household_housing_and_services USING btree (tab_id);


--
-- Name: ix_dbt_register_history_household_programs_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_programs_functional_record_id ON public.dbt_register_history_household_programs USING btree (functional_record_id);


--
-- Name: ix_dbt_register_history_household_programs_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_programs_internal_record_id ON public.dbt_register_history_household_programs USING btree (internal_record_id);


--
-- Name: ix_dbt_register_history_household_programs_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_programs_link_foundational_id ON public.dbt_register_history_household_programs USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_history_household_programs_link_interna_7f4f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_programs_link_interna_7f4f ON public.dbt_register_history_household_programs USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_history_household_programs_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_programs_section_id ON public.dbt_register_history_household_programs USING btree (section_id);


--
-- Name: ix_dbt_register_history_household_programs_subject_inte_593b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_programs_subject_inte_593b ON public.dbt_register_history_household_programs USING btree (subject_internal_record_id);


--
-- Name: ix_dbt_register_history_household_programs_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_programs_submission_id ON public.dbt_register_history_household_programs USING btree (submission_id);


--
-- Name: ix_dbt_register_history_household_programs_tab_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_household_programs_tab_id ON public.dbt_register_history_household_programs USING btree (tab_id);


--
-- Name: ix_dbt_register_history_households_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_households_functional_record_id ON public.dbt_register_history_households USING btree (functional_record_id);


--
-- Name: ix_dbt_register_history_households_household_head_inter_5f3a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_households_household_head_inter_5f3a ON public.dbt_register_history_households USING btree (household_head_internal_record_id);


--
-- Name: ix_dbt_register_history_households_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_households_internal_record_id ON public.dbt_register_history_households USING btree (internal_record_id);


--
-- Name: ix_dbt_register_history_households_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_households_link_foundational_id ON public.dbt_register_history_households USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_history_households_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_households_link_internal_record_id ON public.dbt_register_history_households USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_history_households_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_households_section_id ON public.dbt_register_history_households USING btree (section_id);


--
-- Name: ix_dbt_register_history_households_subject_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_households_subject_internal_record_id ON public.dbt_register_history_households USING btree (subject_internal_record_id);


--
-- Name: ix_dbt_register_history_households_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_households_submission_id ON public.dbt_register_history_households USING btree (submission_id);


--
-- Name: ix_dbt_register_history_households_tab_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_households_tab_id ON public.dbt_register_history_households USING btree (tab_id);


--
-- Name: ix_dbt_register_history_individual_disabilities_disabil_6079; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_disabilities_disabil_6079 ON public.dbt_register_history_individual_disabilities USING btree (disability_domain);


--
-- Name: ix_dbt_register_history_individual_disabilities_functio_5636; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_disabilities_functio_5636 ON public.dbt_register_history_individual_disabilities USING btree (functional_record_id);


--
-- Name: ix_dbt_register_history_individual_disabilities_interna_1a23; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_disabilities_interna_1a23 ON public.dbt_register_history_individual_disabilities USING btree (internal_record_id);


--
-- Name: ix_dbt_register_history_individual_disabilities_link_fo_807b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_disabilities_link_fo_807b ON public.dbt_register_history_individual_disabilities USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_history_individual_disabilities_link_in_1f6e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_disabilities_link_in_1f6e ON public.dbt_register_history_individual_disabilities USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_history_individual_disabilities_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_disabilities_section_id ON public.dbt_register_history_individual_disabilities USING btree (section_id);


--
-- Name: ix_dbt_register_history_individual_disabilities_subject_f70c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_disabilities_subject_f70c ON public.dbt_register_history_individual_disabilities USING btree (subject_internal_record_id);


--
-- Name: ix_dbt_register_history_individual_disabilities_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_disabilities_submission_id ON public.dbt_register_history_individual_disabilities USING btree (submission_id);


--
-- Name: ix_dbt_register_history_individual_disabilities_tab_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_disabilities_tab_id ON public.dbt_register_history_individual_disabilities USING btree (tab_id);


--
-- Name: ix_dbt_register_history_individual_land_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_land_functional_record_id ON public.dbt_register_history_individual_land USING btree (functional_record_id);


--
-- Name: ix_dbt_register_history_individual_land_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_land_internal_record_id ON public.dbt_register_history_individual_land USING btree (internal_record_id);


--
-- Name: ix_dbt_register_history_individual_land_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_land_link_foundational_id ON public.dbt_register_history_individual_land USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_history_individual_land_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_land_link_internal_record_id ON public.dbt_register_history_individual_land USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_history_individual_land_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_land_section_id ON public.dbt_register_history_individual_land USING btree (section_id);


--
-- Name: ix_dbt_register_history_individual_land_subject_interna_b643; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_land_subject_interna_b643 ON public.dbt_register_history_individual_land USING btree (subject_internal_record_id);


--
-- Name: ix_dbt_register_history_individual_land_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_land_submission_id ON public.dbt_register_history_individual_land USING btree (submission_id);


--
-- Name: ix_dbt_register_history_individual_land_tab_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_land_tab_id ON public.dbt_register_history_individual_land USING btree (tab_id);


--
-- Name: ix_dbt_register_history_individual_livelihoods_function_41d1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_livelihoods_function_41d1 ON public.dbt_register_history_individual_livelihoods USING btree (functional_record_id);


--
-- Name: ix_dbt_register_history_individual_livelihoods_internal_cac1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_livelihoods_internal_cac1 ON public.dbt_register_history_individual_livelihoods USING btree (internal_record_id);


--
-- Name: ix_dbt_register_history_individual_livelihoods_link_fou_b6b3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_livelihoods_link_fou_b6b3 ON public.dbt_register_history_individual_livelihoods USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_history_individual_livelihoods_link_int_acac; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_livelihoods_link_int_acac ON public.dbt_register_history_individual_livelihoods USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_history_individual_livelihoods_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_livelihoods_section_id ON public.dbt_register_history_individual_livelihoods USING btree (section_id);


--
-- Name: ix_dbt_register_history_individual_livelihoods_subject__e94f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_livelihoods_subject__e94f ON public.dbt_register_history_individual_livelihoods USING btree (subject_internal_record_id);


--
-- Name: ix_dbt_register_history_individual_livelihoods_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_livelihoods_submission_id ON public.dbt_register_history_individual_livelihoods USING btree (submission_id);


--
-- Name: ix_dbt_register_history_individual_livelihoods_tab_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_livelihoods_tab_id ON public.dbt_register_history_individual_livelihoods USING btree (tab_id);


--
-- Name: ix_dbt_register_history_individual_livestock_functional_3b2a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_livestock_functional_3b2a ON public.dbt_register_history_individual_livestock USING btree (functional_record_id);


--
-- Name: ix_dbt_register_history_individual_livestock_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_livestock_internal_record_id ON public.dbt_register_history_individual_livestock USING btree (internal_record_id);


--
-- Name: ix_dbt_register_history_individual_livestock_link_found_10b3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_livestock_link_found_10b3 ON public.dbt_register_history_individual_livestock USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_history_individual_livestock_link_inter_40fa; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_livestock_link_inter_40fa ON public.dbt_register_history_individual_livestock USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_history_individual_livestock_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_livestock_section_id ON public.dbt_register_history_individual_livestock USING btree (section_id);


--
-- Name: ix_dbt_register_history_individual_livestock_subject_in_5ce5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_livestock_subject_in_5ce5 ON public.dbt_register_history_individual_livestock USING btree (subject_internal_record_id);


--
-- Name: ix_dbt_register_history_individual_livestock_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_livestock_submission_id ON public.dbt_register_history_individual_livestock USING btree (submission_id);


--
-- Name: ix_dbt_register_history_individual_livestock_tab_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_livestock_tab_id ON public.dbt_register_history_individual_livestock USING btree (tab_id);


--
-- Name: ix_dbt_register_history_individual_programs_functional__72ee; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_programs_functional__72ee ON public.dbt_register_history_individual_programs USING btree (functional_record_id);


--
-- Name: ix_dbt_register_history_individual_programs_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_programs_internal_record_id ON public.dbt_register_history_individual_programs USING btree (internal_record_id);


--
-- Name: ix_dbt_register_history_individual_programs_link_founda_91e8; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_programs_link_founda_91e8 ON public.dbt_register_history_individual_programs USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_history_individual_programs_link_intern_020c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_programs_link_intern_020c ON public.dbt_register_history_individual_programs USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_history_individual_programs_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_programs_section_id ON public.dbt_register_history_individual_programs USING btree (section_id);


--
-- Name: ix_dbt_register_history_individual_programs_subject_int_a3ba; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_programs_subject_int_a3ba ON public.dbt_register_history_individual_programs USING btree (subject_internal_record_id);


--
-- Name: ix_dbt_register_history_individual_programs_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_programs_submission_id ON public.dbt_register_history_individual_programs USING btree (submission_id);


--
-- Name: ix_dbt_register_history_individual_programs_tab_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_programs_tab_id ON public.dbt_register_history_individual_programs USING btree (tab_id);


--
-- Name: ix_dbt_register_history_individual_shocks_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_shocks_functional_record_id ON public.dbt_register_history_individual_shocks USING btree (functional_record_id);


--
-- Name: ix_dbt_register_history_individual_shocks_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_shocks_internal_record_id ON public.dbt_register_history_individual_shocks USING btree (internal_record_id);


--
-- Name: ix_dbt_register_history_individual_shocks_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_shocks_link_foundational_id ON public.dbt_register_history_individual_shocks USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_history_individual_shocks_link_internal_cc73; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_shocks_link_internal_cc73 ON public.dbt_register_history_individual_shocks USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_history_individual_shocks_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_shocks_section_id ON public.dbt_register_history_individual_shocks USING btree (section_id);


--
-- Name: ix_dbt_register_history_individual_shocks_shock_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_shocks_shock_date ON public.dbt_register_history_individual_shocks USING btree (shock_date);


--
-- Name: ix_dbt_register_history_individual_shocks_subject_inter_208b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_shocks_subject_inter_208b ON public.dbt_register_history_individual_shocks USING btree (subject_internal_record_id);


--
-- Name: ix_dbt_register_history_individual_shocks_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_shocks_submission_id ON public.dbt_register_history_individual_shocks USING btree (submission_id);


--
-- Name: ix_dbt_register_history_individual_shocks_tab_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_shocks_tab_id ON public.dbt_register_history_individual_shocks USING btree (tab_id);


--
-- Name: ix_dbt_register_history_individual_vulnerability_functi_19ce; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_vulnerability_functi_19ce ON public.dbt_register_history_individual_vulnerability USING btree (functional_record_id);


--
-- Name: ix_dbt_register_history_individual_vulnerability_intern_b1ac; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_vulnerability_intern_b1ac ON public.dbt_register_history_individual_vulnerability USING btree (internal_record_id);


--
-- Name: ix_dbt_register_history_individual_vulnerability_link_f_8eb5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_vulnerability_link_f_8eb5 ON public.dbt_register_history_individual_vulnerability USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_history_individual_vulnerability_link_i_4b28; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_vulnerability_link_i_4b28 ON public.dbt_register_history_individual_vulnerability USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_history_individual_vulnerability_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_vulnerability_section_id ON public.dbt_register_history_individual_vulnerability USING btree (section_id);


--
-- Name: ix_dbt_register_history_individual_vulnerability_subjec_7569; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_vulnerability_subjec_7569 ON public.dbt_register_history_individual_vulnerability USING btree (subject_internal_record_id);


--
-- Name: ix_dbt_register_history_individual_vulnerability_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_vulnerability_submission_id ON public.dbt_register_history_individual_vulnerability USING btree (submission_id);


--
-- Name: ix_dbt_register_history_individual_vulnerability_tab_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individual_vulnerability_tab_id ON public.dbt_register_history_individual_vulnerability USING btree (tab_id);


--
-- Name: ix_dbt_register_history_individuals_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individuals_foundational_id ON public.dbt_register_history_individuals USING btree (foundational_id);


--
-- Name: ix_dbt_register_history_individuals_full_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individuals_full_name ON public.dbt_register_history_individuals USING btree (full_name);


--
-- Name: ix_dbt_register_history_individuals_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individuals_functional_record_id ON public.dbt_register_history_individuals USING btree (functional_record_id);


--
-- Name: ix_dbt_register_history_individuals_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individuals_internal_record_id ON public.dbt_register_history_individuals USING btree (internal_record_id);


--
-- Name: ix_dbt_register_history_individuals_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individuals_link_foundational_id ON public.dbt_register_history_individuals USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_history_individuals_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individuals_link_internal_record_id ON public.dbt_register_history_individuals USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_history_individuals_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individuals_section_id ON public.dbt_register_history_individuals USING btree (section_id);


--
-- Name: ix_dbt_register_history_individuals_subject_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individuals_subject_internal_record_id ON public.dbt_register_history_individuals USING btree (subject_internal_record_id);


--
-- Name: ix_dbt_register_history_individuals_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individuals_submission_id ON public.dbt_register_history_individuals USING btree (submission_id);


--
-- Name: ix_dbt_register_history_individuals_tab_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_history_individuals_tab_id ON public.dbt_register_history_individuals USING btree (tab_id);


--
-- Name: ix_dbt_register_household_assets_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_register_household_assets_functional_record_id ON public.dbt_register_household_assets USING btree (functional_record_id);


--
-- Name: ix_dbt_register_household_assets_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_household_assets_link_foundational_id ON public.dbt_register_household_assets USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_household_assets_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_household_assets_link_internal_record_id ON public.dbt_register_household_assets USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_household_housing_and_services_function_063c; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_register_household_housing_and_services_function_063c ON public.dbt_register_household_housing_and_services USING btree (functional_record_id);


--
-- Name: ix_dbt_register_household_housing_and_services_link_fou_c787; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_household_housing_and_services_link_fou_c787 ON public.dbt_register_household_housing_and_services USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_household_housing_and_services_link_int_b3a1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_household_housing_and_services_link_int_b3a1 ON public.dbt_register_household_housing_and_services USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_household_programs_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_register_household_programs_functional_record_id ON public.dbt_register_household_programs USING btree (functional_record_id);


--
-- Name: ix_dbt_register_household_programs_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_household_programs_link_foundational_id ON public.dbt_register_household_programs USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_household_programs_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_household_programs_link_internal_record_id ON public.dbt_register_household_programs USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_households_country_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_households_country_code ON public.dbt_register_households USING btree (country_code);


--
-- Name: ix_dbt_register_households_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_register_households_functional_record_id ON public.dbt_register_households USING btree (functional_record_id);


--
-- Name: ix_dbt_register_households_geo_lowest_level_value_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_households_geo_lowest_level_value_id ON public.dbt_register_households USING btree (geo_lowest_level_value_id);


--
-- Name: ix_dbt_register_households_household_head_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_households_household_head_internal_record_id ON public.dbt_register_households USING btree (household_head_internal_record_id);


--
-- Name: ix_dbt_register_households_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_households_link_foundational_id ON public.dbt_register_households USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_households_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_households_link_internal_record_id ON public.dbt_register_households USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_households_plus_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_households_plus_code ON public.dbt_register_households USING btree (plus_code);


--
-- Name: ix_dbt_register_households_postal_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_households_postal_code ON public.dbt_register_households USING btree (postal_code);


--
-- Name: ix_dbt_register_individual_disabilities_disability_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individual_disabilities_disability_domain ON public.dbt_register_individual_disabilities USING btree (disability_domain);


--
-- Name: ix_dbt_register_individual_disabilities_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_register_individual_disabilities_functional_record_id ON public.dbt_register_individual_disabilities USING btree (functional_record_id);


--
-- Name: ix_dbt_register_individual_disabilities_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individual_disabilities_link_foundational_id ON public.dbt_register_individual_disabilities USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_individual_disabilities_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individual_disabilities_link_internal_record_id ON public.dbt_register_individual_disabilities USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_individual_land_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_register_individual_land_functional_record_id ON public.dbt_register_individual_land USING btree (functional_record_id);


--
-- Name: ix_dbt_register_individual_land_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individual_land_link_foundational_id ON public.dbt_register_individual_land USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_individual_land_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individual_land_link_internal_record_id ON public.dbt_register_individual_land USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_individual_livelihoods_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_register_individual_livelihoods_functional_record_id ON public.dbt_register_individual_livelihoods USING btree (functional_record_id);


--
-- Name: ix_dbt_register_individual_livelihoods_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individual_livelihoods_link_foundational_id ON public.dbt_register_individual_livelihoods USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_individual_livelihoods_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individual_livelihoods_link_internal_record_id ON public.dbt_register_individual_livelihoods USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_individual_livestock_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_register_individual_livestock_functional_record_id ON public.dbt_register_individual_livestock USING btree (functional_record_id);


--
-- Name: ix_dbt_register_individual_livestock_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individual_livestock_link_foundational_id ON public.dbt_register_individual_livestock USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_individual_livestock_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individual_livestock_link_internal_record_id ON public.dbt_register_individual_livestock USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_individual_programs_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_register_individual_programs_functional_record_id ON public.dbt_register_individual_programs USING btree (functional_record_id);


--
-- Name: ix_dbt_register_individual_programs_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individual_programs_link_foundational_id ON public.dbt_register_individual_programs USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_individual_programs_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individual_programs_link_internal_record_id ON public.dbt_register_individual_programs USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_individual_shocks_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_register_individual_shocks_functional_record_id ON public.dbt_register_individual_shocks USING btree (functional_record_id);


--
-- Name: ix_dbt_register_individual_shocks_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individual_shocks_link_foundational_id ON public.dbt_register_individual_shocks USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_individual_shocks_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individual_shocks_link_internal_record_id ON public.dbt_register_individual_shocks USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_individual_shocks_shock_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individual_shocks_shock_date ON public.dbt_register_individual_shocks USING btree (shock_date);


--
-- Name: ix_dbt_register_individual_vulnerability_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_register_individual_vulnerability_functional_record_id ON public.dbt_register_individual_vulnerability USING btree (functional_record_id);


--
-- Name: ix_dbt_register_individual_vulnerability_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individual_vulnerability_link_foundational_id ON public.dbt_register_individual_vulnerability USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_individual_vulnerability_link_internal__7e9f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individual_vulnerability_link_internal__7e9f ON public.dbt_register_individual_vulnerability USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_individuals_country_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individuals_country_code ON public.dbt_register_individuals USING btree (country_code);


--
-- Name: ix_dbt_register_individuals_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individuals_foundational_id ON public.dbt_register_individuals USING btree (foundational_id);


--
-- Name: ix_dbt_register_individuals_full_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individuals_full_name ON public.dbt_register_individuals USING btree (full_name);


--
-- Name: ix_dbt_register_individuals_functional_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_register_individuals_functional_record_id ON public.dbt_register_individuals USING btree (functional_record_id);


--
-- Name: ix_dbt_register_individuals_geo_lowest_level_value_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individuals_geo_lowest_level_value_id ON public.dbt_register_individuals USING btree (geo_lowest_level_value_id);


--
-- Name: ix_dbt_register_individuals_link_foundational_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individuals_link_foundational_id ON public.dbt_register_individuals USING btree (link_foundational_id);


--
-- Name: ix_dbt_register_individuals_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individuals_link_internal_record_id ON public.dbt_register_individuals USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_individuals_plus_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individuals_plus_code ON public.dbt_register_individuals USING btree (plus_code);


--
-- Name: ix_dbt_register_individuals_postal_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_individuals_postal_code ON public.dbt_register_individuals USING btree (postal_code);


--
-- Name: ix_dbt_register_score_contributing_attributes_register_mnemonic; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_score_contributing_attributes_register_mnemonic ON public.dbt_register_score_contributing_attributes USING btree (register_mnemonic);


--
-- Name: ix_dbt_register_score_contributing_attributes_score_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_score_contributing_attributes_score_type ON public.dbt_register_score_contributing_attributes USING btree (score_type);


--
-- Name: ix_dbt_register_score_def_reg_mnem_score_type_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_register_score_def_reg_mnem_score_type_unique ON public.dbt_register_score_definitions USING btree (register_mnemonic, score_type);


--
-- Name: ix_dbt_register_score_definitions_register_mnemonic; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_score_definitions_register_mnemonic ON public.dbt_register_score_definitions USING btree (register_mnemonic);


--
-- Name: ix_dbt_register_score_definitions_score_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_score_definitions_score_type ON public.dbt_register_score_definitions USING btree (score_type);


--
-- Name: ix_dbt_register_score_history_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_score_history_link_internal_record_id ON public.dbt_register_score_history USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_score_history_link_rec_id_score_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_score_history_link_rec_id_score_type ON public.dbt_register_score_history USING btree (link_internal_record_id, score_type);


--
-- Name: ix_dbt_register_score_history_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_score_history_register_id ON public.dbt_register_score_history USING btree (register_id);


--
-- Name: ix_dbt_register_score_history_score_definition_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_score_history_score_definition_id ON public.dbt_register_score_history USING btree (score_definition_id);


--
-- Name: ix_dbt_register_score_history_score_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_score_history_score_type ON public.dbt_register_score_history USING btree (score_type);


--
-- Name: ix_dbt_register_score_history_triggered_by_cr_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_score_history_triggered_by_cr_id ON public.dbt_register_score_history USING btree (triggered_by_cr_id);


--
-- Name: ix_dbt_register_score_history_triggered_by_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_score_history_triggered_by_submission_id ON public.dbt_register_score_history USING btree (triggered_by_submission_id);


--
-- Name: ix_dbt_register_scores_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_scores_link_internal_record_id ON public.dbt_register_scores USING btree (link_internal_record_id);


--
-- Name: ix_dbt_register_scores_link_internal_record_id_score_type; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_register_scores_link_internal_record_id_score_type ON public.dbt_register_scores USING btree (link_internal_record_id, score_type);


--
-- Name: ix_dbt_register_scores_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_scores_register_id ON public.dbt_register_scores USING btree (register_id);


--
-- Name: ix_dbt_register_scores_score_definition_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_scores_score_definition_id ON public.dbt_register_scores USING btree (score_definition_id);


--
-- Name: ix_dbt_register_scores_score_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_scores_score_type ON public.dbt_register_scores USING btree (score_type);


--
-- Name: ix_dbt_register_scores_triggered_by_cr_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_scores_triggered_by_cr_id ON public.dbt_register_scores USING btree (triggered_by_cr_id);


--
-- Name: ix_dbt_register_scores_triggered_by_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_scores_triggered_by_submission_id ON public.dbt_register_scores USING btree (triggered_by_submission_id);


--
-- Name: ix_dbt_register_section_completion_score_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_section_completion_score_internal_record_id ON public.dbt_register_section_completion_score USING btree (internal_record_id);


--
-- Name: ix_dbt_register_section_completion_score_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_section_completion_score_register_id ON public.dbt_register_section_completion_score USING btree (register_id);


--
-- Name: ix_dbt_register_section_completion_score_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_section_completion_score_section_id ON public.dbt_register_section_completion_score USING btree (section_id);


--
-- Name: ix_dbt_register_section_documents_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_section_documents_document_id ON public.dbt_register_section_documents USING btree (document_id);


--
-- Name: ix_dbt_register_section_documents_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_section_documents_internal_record_id ON public.dbt_register_section_documents USING btree (internal_record_id);


--
-- Name: ix_dbt_register_section_documents_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_section_documents_section_id ON public.dbt_register_section_documents USING btree (section_id);


--
-- Name: ix_dbt_register_sections_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_sections_register_id ON public.dbt_register_sections USING btree (register_id);


--
-- Name: ix_dbt_register_sections_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_sections_section_id ON public.dbt_register_sections USING btree (section_id);


--
-- Name: ix_dbt_register_sections_section_mnemonic; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_register_sections_section_mnemonic ON public.dbt_register_sections USING btree (section_mnemonic);


--
-- Name: ix_dbt_register_sections_section_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_sections_section_register_id ON public.dbt_register_sections USING btree (section_register_id);


--
-- Name: ix_dbt_register_ui_tab_sections_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_ui_tab_sections_register_id ON public.dbt_register_ui_tab_sections USING btree (register_id);


--
-- Name: ix_dbt_register_ui_tab_sections_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_ui_tab_sections_section_id ON public.dbt_register_ui_tab_sections USING btree (section_id);


--
-- Name: ix_dbt_register_ui_tab_sections_tab_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_ui_tab_sections_tab_id ON public.dbt_register_ui_tab_sections USING btree (tab_id);


--
-- Name: ix_dbt_register_ui_tabs_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_ui_tabs_register_id ON public.dbt_register_ui_tabs USING btree (register_id);


--
-- Name: ix_dbt_register_verifications_change_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_verifications_change_request_id ON public.dbt_register_verifications USING btree (change_request_id);


--
-- Name: ix_dbt_register_verifications_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_verifications_internal_record_id ON public.dbt_register_verifications USING btree (internal_record_id);


--
-- Name: ix_dbt_register_verifications_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_verifications_register_id ON public.dbt_register_verifications USING btree (register_id);


--
-- Name: ix_dbt_register_verifications_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_verifications_section_id ON public.dbt_register_verifications USING btree (section_id);


--
-- Name: ix_dbt_register_verifications_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_register_verifications_submission_id ON public.dbt_register_verifications USING btree (submission_id);


--
-- Name: ix_dbt_registrant_authentication_providers_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registrant_authentication_providers_register_id ON public.dbt_registrant_authentication_providers USING btree (register_id);


--
-- Name: ix_dbt_registrant_authentications_expiry_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registrant_authentications_expiry_at ON public.dbt_registrant_authentications USING btree (expiry_at);


--
-- Name: ix_dbt_registrant_authentications_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registrant_authentications_internal_record_id ON public.dbt_registrant_authentications USING btree (internal_record_id);


--
-- Name: ix_dbt_registrant_authentications_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registrant_authentications_provider_id ON public.dbt_registrant_authentications USING btree (provider_id);


--
-- Name: ix_dbt_registrant_authentications_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registrant_authentications_register_id ON public.dbt_registrant_authentications USING btree (register_id);


--
-- Name: ix_dbt_registrant_authentications_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registrant_authentications_status ON public.dbt_registrant_authentications USING btree (status);


--
-- Name: ix_dbt_registry_awe_policy_configurations_awe_policy_config_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_awe_policy_configurations_awe_policy_config_id ON public.dbt_registry_awe_policy_configurations USING btree (awe_policy_config_id);


--
-- Name: ix_dbt_registry_awe_policy_configurations_intake_form_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_awe_policy_configurations_intake_form_id ON public.dbt_registry_awe_policy_configurations USING btree (intake_form_id);


--
-- Name: ix_dbt_registry_awe_policy_configurations_policy_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_awe_policy_configurations_policy_key ON public.dbt_registry_awe_policy_configurations USING btree (policy_key);


--
-- Name: ix_dbt_registry_awe_policy_configurations_policy_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_awe_policy_configurations_policy_scope ON public.dbt_registry_awe_policy_configurations USING btree (policy_scope);


--
-- Name: ix_dbt_registry_awe_policy_configurations_policy_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_awe_policy_configurations_policy_type ON public.dbt_registry_awe_policy_configurations USING btree (policy_type);


--
-- Name: ix_dbt_registry_awe_policy_configurations_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_awe_policy_configurations_register_id ON public.dbt_registry_awe_policy_configurations USING btree (register_id);


--
-- Name: ix_dbt_registry_awe_policy_configurations_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_awe_policy_configurations_section_id ON public.dbt_registry_awe_policy_configurations USING btree (section_id);


--
-- Name: ix_dbt_registry_data_policies_mnemonic_target_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_registry_data_policies_mnemonic_target_unique ON public.dbt_registry_data_policies USING btree (policy_mnemonic, policy_target) WHERE (register_id IS NULL);


--
-- Name: ix_dbt_registry_data_policies_policy_mnemonic; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_data_policies_policy_mnemonic ON public.dbt_registry_data_policies USING btree (policy_mnemonic);


--
-- Name: ix_dbt_registry_data_policies_policy_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_data_policies_policy_target ON public.dbt_registry_data_policies USING btree (policy_target);


--
-- Name: ix_dbt_registry_data_policies_reg_mnemonic_target_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_registry_data_policies_reg_mnemonic_target_unique ON public.dbt_registry_data_policies USING btree (register_id, policy_mnemonic, policy_target) WHERE (register_id IS NOT NULL);


--
-- Name: ix_dbt_registry_data_policies_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_data_policies_register_id ON public.dbt_registry_data_policies USING btree (register_id);


--
-- Name: ix_dbt_registry_documents_bucket; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_documents_bucket ON public.dbt_registry_documents USING btree (bucket);


--
-- Name: ix_dbt_registry_documents_document_store_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dbt_registry_documents_document_store_id ON public.dbt_registry_documents USING btree (document_store_id);


--
-- Name: ix_dbt_registry_import_file_configurations_data_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_import_file_configurations_data_model_id ON public.dbt_registry_import_file_configurations USING btree (data_model_id);


--
-- Name: ix_dbt_registry_import_file_configurations_form_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_import_file_configurations_form_id ON public.dbt_registry_import_file_configurations USING btree (form_id);


--
-- Name: ix_dbt_registry_import_file_configurations_import_file__711e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_import_file_configurations_import_file__711e ON public.dbt_registry_import_file_configurations USING btree (import_file_template_mnemonic);


--
-- Name: ix_dbt_registry_import_file_configurations_import_file__7c4c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_import_file_configurations_import_file__7c4c ON public.dbt_registry_import_file_configurations USING btree (import_file_configuration_id);


--
-- Name: ix_dbt_registry_import_file_configurations_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_import_file_configurations_register_id ON public.dbt_registry_import_file_configurations USING btree (register_id);


--
-- Name: ix_dbt_registry_vc_configurations_data_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_vc_configurations_data_model_id ON public.dbt_registry_vc_configurations USING btree (data_model_id);


--
-- Name: ix_dbt_registry_vc_configurations_intake_form_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_vc_configurations_intake_form_id ON public.dbt_registry_vc_configurations USING btree (intake_form_id);


--
-- Name: ix_dbt_registry_vc_configurations_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_vc_configurations_register_id ON public.dbt_registry_vc_configurations USING btree (register_id);


--
-- Name: ix_dbt_registry_vc_configurations_vc_config_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_vc_configurations_vc_config_id ON public.dbt_registry_vc_configurations USING btree (vc_config_id);


--
-- Name: ix_dbt_registry_vc_configurations_vc_mnemonic; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_registry_vc_configurations_vc_mnemonic ON public.dbt_registry_vc_configurations USING btree (vc_mnemonic);


--
-- Name: ix_dbt_score_compute_queue_change_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_score_compute_queue_change_request_id ON public.dbt_score_compute_queue USING btree (change_request_id);


--
-- Name: ix_dbt_score_compute_queue_compute_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_score_compute_queue_compute_status ON public.dbt_score_compute_queue USING btree (compute_status);


--
-- Name: ix_dbt_score_compute_queue_link_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_score_compute_queue_link_internal_record_id ON public.dbt_score_compute_queue USING btree (link_internal_record_id);


--
-- Name: ix_dbt_score_compute_queue_link_rec_id_score_type_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_score_compute_queue_link_rec_id_score_type_status ON public.dbt_score_compute_queue USING btree (link_internal_record_id, score_type, compute_status);


--
-- Name: ix_dbt_score_compute_queue_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_score_compute_queue_register_id ON public.dbt_score_compute_queue USING btree (register_id);


--
-- Name: ix_dbt_score_compute_queue_score_definition_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_score_compute_queue_score_definition_id ON public.dbt_score_compute_queue USING btree (score_definition_id);


--
-- Name: ix_dbt_score_compute_queue_score_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_score_compute_queue_score_type ON public.dbt_score_compute_queue USING btree (score_type);


--
-- Name: ix_dbt_score_compute_queue_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dbt_score_compute_queue_submission_id ON public.dbt_score_compute_queue USING btree (submission_id);


--
-- Name: ix_import_file_process_log_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_file_process_log_document_id ON public.import_file_process_log USING btree (document_id);


--
-- Name: ix_import_file_process_log_import_file_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_file_process_log_import_file_id ON public.import_file_process_log USING btree (import_file_id);


--
-- Name: ix_import_file_process_log_ingestion_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_file_process_log_ingestion_timestamp ON public.import_file_process_log USING btree (ingestion_timestamp);


--
-- Name: ix_import_file_process_queue_data_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_file_process_queue_data_model_id ON public.import_file_process_queue USING btree (data_model_id);


--
-- Name: ix_import_file_process_queue_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_import_file_process_queue_document_id ON public.import_file_process_queue USING btree (document_id);


--
-- Name: ix_import_file_process_queue_intake_form_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_file_process_queue_intake_form_id ON public.import_file_process_queue USING btree (intake_form_id);


--
-- Name: ix_import_file_process_queue_intake_form_ingestion_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_file_process_queue_intake_form_ingestion_status ON public.import_file_process_queue USING btree (intake_form_ingestion_status);


--
-- Name: ix_import_file_process_queue_queued_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_file_process_queue_queued_at ON public.import_file_process_queue USING btree (queued_at);


--
-- Name: ix_import_file_process_queue_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_file_process_queue_register_id ON public.import_file_process_queue USING btree (register_id);


--
-- Name: ix_incoming_classified_data_change_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_classified_data_change_request_id ON public.incoming_classified_data USING btree (change_request_id);


--
-- Name: ix_incoming_classified_data_data_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_classified_data_data_model_id ON public.incoming_classified_data USING btree (data_model_id);


--
-- Name: ix_incoming_classified_data_ingest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_classified_data_ingest_id ON public.incoming_classified_data USING btree (ingest_id);


--
-- Name: ix_incoming_classified_data_ingestion_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_classified_data_ingestion_status ON public.incoming_classified_data USING btree (ingestion_status);


--
-- Name: ix_incoming_classified_data_intake_form_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_classified_data_intake_form_id ON public.incoming_classified_data USING btree (intake_form_id);


--
-- Name: ix_incoming_classified_data_intake_form_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_classified_data_intake_form_submission_id ON public.incoming_classified_data USING btree (intake_form_submission_id);


--
-- Name: ix_incoming_classified_data_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_classified_data_internal_record_id ON public.incoming_classified_data USING btree (internal_record_id);


--
-- Name: ix_incoming_classified_data_partner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_classified_data_partner_id ON public.incoming_classified_data USING btree (partner_id);


--
-- Name: ix_incoming_classified_data_pipeline_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_classified_data_pipeline_action ON public.incoming_classified_data USING btree (pipeline_action);


--
-- Name: ix_incoming_classified_data_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_classified_data_register_id ON public.incoming_classified_data USING btree (register_id);


--
-- Name: ix_incoming_classified_data_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_classified_data_section_id ON public.incoming_classified_data USING btree (section_id);


--
-- Name: ix_incoming_classified_data_semantic_pattern_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_classified_data_semantic_pattern_id ON public.incoming_classified_data USING btree (semantic_pattern_id);


--
-- Name: ix_incoming_classified_data_transformation_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_classified_data_transformation_status ON public.incoming_classified_data USING btree (transformation_status);


--
-- Name: ix_incoming_enriched_transformed_data_ingest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_enriched_transformed_data_ingest_id ON public.incoming_enriched_transformed_data USING btree (ingest_id);


--
-- Name: ix_incoming_model_key_paths_data_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_incoming_model_key_paths_data_model_id ON public.incoming_model_key_paths USING btree (data_model_id);


--
-- Name: ix_incoming_model_register_semantic_data_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_model_register_semantic_data_model ON public.incoming_model_register_semantic_patterns USING btree (data_model_id);


--
-- Name: ix_incoming_model_register_semantic_patterns_data_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_model_register_semantic_patterns_data_model_id ON public.incoming_model_register_semantic_patterns USING btree (data_model_id);


--
-- Name: ix_incoming_model_register_semantic_patterns_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_model_register_semantic_patterns_register_id ON public.incoming_model_register_semantic_patterns USING btree (register_id);


--
-- Name: ix_incoming_model_semantic_patterns_data_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_model_semantic_patterns_data_model_id ON public.incoming_model_semantic_patterns USING btree (data_model_id);


--
-- Name: ix_incoming_model_semantic_patterns_intake_form_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_model_semantic_patterns_intake_form_id ON public.incoming_model_semantic_patterns USING btree (intake_form_id);


--
-- Name: ix_incoming_model_semantic_patterns_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_model_semantic_patterns_section_id ON public.incoming_model_semantic_patterns USING btree (section_id);


--
-- Name: ix_incoming_raw_data_classification_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_raw_data_classification_status ON public.incoming_raw_data USING btree (classification_status);


--
-- Name: ix_incoming_raw_data_data_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_raw_data_data_model_id ON public.incoming_raw_data USING btree (data_model_id);


--
-- Name: ix_incoming_raw_data_ingest_correlation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_raw_data_ingest_correlation_id ON public.incoming_raw_data USING btree (ingest_correlation_id);


--
-- Name: ix_incoming_raw_data_ingest_message_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_raw_data_ingest_message_id ON public.incoming_raw_data USING btree (ingest_message_id);


--
-- Name: ix_incoming_raw_data_partner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_raw_data_partner_id ON public.incoming_raw_data USING btree (partner_id);


--
-- Name: ix_incoming_raw_data_payloads_ingest_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_raw_data_payloads_ingest_id ON public.incoming_raw_data_payloads USING btree (ingest_id);


--
-- Name: ix_incoming_raw_data_payloads_raw_data_text_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_raw_data_payloads_raw_data_text_gin ON public.incoming_raw_data_payloads USING gin (raw_data_text public.gin_trgm_ops);


--
-- Name: ix_incoming_templates_data_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_templates_data_model_id ON public.incoming_templates USING btree (data_model_id);


--
-- Name: ix_incoming_templates_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_incoming_templates_register_id ON public.incoming_templates USING btree (register_id);


--
-- Name: ix_outgoing_raw_data_change_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_raw_data_change_request_id ON public.outgoing_raw_data USING btree (change_request_id);


--
-- Name: ix_outgoing_raw_data_changed_by_partner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_raw_data_changed_by_partner_id ON public.outgoing_raw_data USING btree (changed_by_partner_id);


--
-- Name: ix_outgoing_raw_data_data_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_raw_data_data_model_id ON public.outgoing_raw_data USING btree (data_model_id);


--
-- Name: ix_outgoing_raw_data_intake_form_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_raw_data_intake_form_submission_id ON public.outgoing_raw_data USING btree (intake_form_submission_id);


--
-- Name: ix_outgoing_raw_data_internal_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_raw_data_internal_record_id ON public.outgoing_raw_data USING btree (internal_record_id);


--
-- Name: ix_outgoing_raw_data_payload_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_raw_data_payload_id ON public.outgoing_raw_data USING btree (payload_id);


--
-- Name: ix_outgoing_raw_data_payloads_change_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_raw_data_payloads_change_request_id ON public.outgoing_raw_data_payloads USING btree (change_request_id);


--
-- Name: ix_outgoing_raw_data_payloads_intake_form_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_raw_data_payloads_intake_form_submission_id ON public.outgoing_raw_data_payloads USING btree (intake_form_submission_id);


--
-- Name: ix_outgoing_raw_data_payloads_raw_data_text_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_raw_data_payloads_raw_data_text_gin ON public.outgoing_raw_data_payloads USING gin (raw_data_text public.gin_trgm_ops);


--
-- Name: ix_outgoing_raw_data_publish_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_raw_data_publish_status ON public.outgoing_raw_data USING btree (publish_status);


--
-- Name: ix_outgoing_raw_data_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_raw_data_register_id ON public.outgoing_raw_data USING btree (register_id);


--
-- Name: ix_outgoing_raw_data_topic_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_raw_data_topic_id ON public.outgoing_raw_data USING btree (topic_id);


--
-- Name: ix_outgoing_raw_data_transformation_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_raw_data_transformation_status ON public.outgoing_raw_data USING btree (transformation_status);


--
-- Name: ix_outgoing_templates_data_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_templates_data_model_id ON public.outgoing_templates USING btree (data_model_id);


--
-- Name: ix_outgoing_templates_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_templates_register_id ON public.outgoing_templates USING btree (register_id);


--
-- Name: ix_outgoing_topics_data_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_topics_data_model_id ON public.outgoing_topics USING btree (data_model_id);


--
-- Name: ix_outgoing_topics_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_topics_register_id ON public.outgoing_topics USING btree (register_id);


--
-- Name: ix_outgoing_transformed_data_payloads_change_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_transformed_data_payloads_change_request_id ON public.outgoing_transformed_data_payloads USING btree (change_request_id);


--
-- Name: ix_outgoing_transformed_data_payloads_intake_form_submission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_transformed_data_payloads_intake_form_submission_id ON public.outgoing_transformed_data_payloads USING btree (intake_form_submission_id);


--
-- Name: ix_outgoing_transformed_data_payloads_payload_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outgoing_transformed_data_payloads_payload_id ON public.outgoing_transformed_data_payloads USING btree (payload_id);


--
-- Name: ix_subscription_activity_logs_partner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subscription_activity_logs_partner_id ON public.subscription_activity_logs USING btree (partner_id);


--
-- Name: ux_import_file_process_log_document_id_record_number; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_import_file_process_log_document_id_record_number ON public.import_file_process_log USING btree (document_id, record_number);


--
-- PostgreSQL database dump complete
--

