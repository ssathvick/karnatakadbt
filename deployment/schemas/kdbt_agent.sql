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
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA public;


--
-- Name: tokenendpointauthmethod; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.tokenendpointauthmethod AS ENUM (
    'private_key_jwt',
    'private_key_jwt_keymanager',
    'client_secret_basic',
    'client_secret_post'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: data_policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_policies (
    policy_id character varying NOT NULL,
    policy_mnemonic character varying NOT NULL,
    policy_description character varying,
    register_id character varying,
    policy_target character varying NOT NULL,
    policy_type character varying NOT NULL,
    policy_filter_expression json NOT NULL,
    application_id integer
);


--
-- Name: login_providers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.login_providers (
    id integer NOT NULL,
    provider_name character varying NOT NULL,
    description character varying,
    icon_base64 character varying,
    client_id character varying NOT NULL,
    client_secret character varying,
    client_private_key bytea,
    token_endpoint_auth_method public.tokenendpointauthmethod NOT NULL,
    keymanager_app_id character varying,
    keymanager_ref_id character varying,
    authorization_endpoint character varying,
    userinfo_endpoint character varying,
    token_endpoint character varying,
    server_metadata_url character varying,
    adapter_name character varying,
    jwks_uri character varying,
    jwt_assertion_aud character varying,
    scope character varying,
    enable_pkce boolean,
    extra_authorize_params character varying,
    issuer character varying NOT NULL,
    audiences character varying,
    oauth_callback_url character varying NOT NULL,
    default_redirect_uri character varying,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone,
    active boolean NOT NULL
);


--
-- Name: login_providers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.login_providers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: login_providers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.login_providers_id_seq OWNED BY public.login_providers.id;


--
-- Name: staff_application_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.staff_application_permissions (
    permission_mnemonic character varying NOT NULL,
    permission_description character varying,
    application_id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone,
    id integer NOT NULL,
    active boolean NOT NULL
);


--
-- Name: staff_application_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.staff_application_permissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: staff_application_permissions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.staff_application_permissions_id_seq OWNED BY public.staff_application_permissions.id;


--
-- Name: staff_portal_applications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.staff_portal_applications (
    application_mnemonic character varying NOT NULL,
    application_description character varying,
    icon_base64 character varying,
    width integer,
    application_url character varying,
    api_url character varying,
    "order" integer,
    is_self_registered boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone,
    id integer NOT NULL,
    active boolean NOT NULL
);


--
-- Name: staff_portal_applications_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.staff_portal_applications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: staff_portal_applications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.staff_portal_applications_id_seq OWNED BY public.staff_portal_applications.id;


--
-- Name: staff_role_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.staff_role_permissions (
    role_id integer NOT NULL,
    permission_id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone,
    id integer NOT NULL,
    active boolean NOT NULL
);


--
-- Name: staff_role_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.staff_role_permissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: staff_role_permissions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.staff_role_permissions_id_seq OWNED BY public.staff_role_permissions.id;


--
-- Name: staff_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.staff_roles (
    role_mnemonic character varying NOT NULL,
    role_description character varying,
    application_id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone,
    id integer NOT NULL,
    active boolean NOT NULL
);


--
-- Name: staff_roles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.staff_roles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: staff_roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.staff_roles_id_seq OWNED BY public.staff_roles.id;


--
-- Name: login_providers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.login_providers ALTER COLUMN id SET DEFAULT nextval('public.login_providers_id_seq'::regclass);


--
-- Name: staff_application_permissions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff_application_permissions ALTER COLUMN id SET DEFAULT nextval('public.staff_application_permissions_id_seq'::regclass);


--
-- Name: staff_portal_applications id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff_portal_applications ALTER COLUMN id SET DEFAULT nextval('public.staff_portal_applications_id_seq'::regclass);


--
-- Name: staff_role_permissions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff_role_permissions ALTER COLUMN id SET DEFAULT nextval('public.staff_role_permissions_id_seq'::regclass);


--
-- Name: staff_roles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff_roles ALTER COLUMN id SET DEFAULT nextval('public.staff_roles_id_seq'::regclass);


--
-- Name: data_policies data_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_policies
    ADD CONSTRAINT data_policies_pkey PRIMARY KEY (policy_id);


--
-- Name: login_providers login_providers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.login_providers
    ADD CONSTRAINT login_providers_pkey PRIMARY KEY (id);


--
-- Name: staff_application_permissions staff_application_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff_application_permissions
    ADD CONSTRAINT staff_application_permissions_pkey PRIMARY KEY (id);


--
-- Name: staff_portal_applications staff_portal_applications_application_mnemonic_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff_portal_applications
    ADD CONSTRAINT staff_portal_applications_application_mnemonic_key UNIQUE (application_mnemonic);


--
-- Name: staff_portal_applications staff_portal_applications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff_portal_applications
    ADD CONSTRAINT staff_portal_applications_pkey PRIMARY KEY (id);


--
-- Name: staff_role_permissions staff_role_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff_role_permissions
    ADD CONSTRAINT staff_role_permissions_pkey PRIMARY KEY (id);


--
-- Name: staff_roles staff_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff_roles
    ADD CONSTRAINT staff_roles_pkey PRIMARY KEY (id);


--
-- Name: ix_data_policies_mnemonic_target_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_data_policies_mnemonic_target_unique ON public.data_policies USING btree (policy_mnemonic, policy_target) WHERE (register_id IS NULL);


--
-- Name: ix_data_policies_policy_mnemonic; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_data_policies_policy_mnemonic ON public.data_policies USING btree (policy_mnemonic);


--
-- Name: ix_data_policies_policy_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_data_policies_policy_target ON public.data_policies USING btree (policy_target);


--
-- Name: ix_data_policies_reg_mnemonic_target_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_data_policies_reg_mnemonic_target_unique ON public.data_policies USING btree (register_id, policy_mnemonic, policy_target) WHERE (register_id IS NOT NULL);


--
-- Name: ix_data_policies_register_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_data_policies_register_id ON public.data_policies USING btree (register_id);


--
-- Name: data_policies kdbt_producer_fence; Type: TRIGGER; Schema: public; Owner: -
--



--
-- Name: login_providers kdbt_producer_fence; Type: TRIGGER; Schema: public; Owner: -
--



--
-- Name: staff_application_permissions kdbt_producer_fence; Type: TRIGGER; Schema: public; Owner: -
--



--
-- Name: staff_portal_applications kdbt_producer_fence; Type: TRIGGER; Schema: public; Owner: -
--



--
-- Name: staff_role_permissions kdbt_producer_fence; Type: TRIGGER; Schema: public; Owner: -
--



--
-- Name: staff_roles kdbt_producer_fence; Type: TRIGGER; Schema: public; Owner: -
--



--
-- Name: data_policies kdbt_registry_capture; Type: TRIGGER; Schema: public; Owner: -
--



--
-- Name: login_providers kdbt_registry_capture; Type: TRIGGER; Schema: public; Owner: -
--



--
-- Name: staff_application_permissions kdbt_registry_capture; Type: TRIGGER; Schema: public; Owner: -
--



--
-- Name: staff_portal_applications kdbt_registry_capture; Type: TRIGGER; Schema: public; Owner: -
--



--
-- Name: staff_role_permissions kdbt_registry_capture; Type: TRIGGER; Schema: public; Owner: -
--



--
-- Name: staff_roles kdbt_registry_capture; Type: TRIGGER; Schema: public; Owner: -
--



--
-- Name: data_policies kdbt_registry_capture_truncate; Type: TRIGGER; Schema: public; Owner: -
--



--
-- Name: login_providers kdbt_registry_capture_truncate; Type: TRIGGER; Schema: public; Owner: -
--



--
-- Name: staff_application_permissions kdbt_registry_capture_truncate; Type: TRIGGER; Schema: public; Owner: -
--



--
-- Name: staff_portal_applications kdbt_registry_capture_truncate; Type: TRIGGER; Schema: public; Owner: -
--



--
-- Name: staff_role_permissions kdbt_registry_capture_truncate; Type: TRIGGER; Schema: public; Owner: -
--



--
-- Name: staff_roles kdbt_registry_capture_truncate; Type: TRIGGER; Schema: public; Owner: -
--



--
-- PostgreSQL database dump complete
--

