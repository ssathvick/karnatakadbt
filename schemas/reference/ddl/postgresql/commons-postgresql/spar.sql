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
-- Name: banks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.banks (
    bank_mnemonic character varying(50) NOT NULL,
    bank_name character varying(255) NOT NULL,
    bank_code character varying(50) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone,
    id integer NOT NULL,
    active boolean NOT NULL
);


--
-- Name: banks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.banks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: banks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.banks_id_seq OWNED BY public.banks.id;


--
-- Name: branches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.branches (
    branch_mnemonic character varying(50) NOT NULL,
    branch_name character varying(255) NOT NULL,
    branch_code character varying(50) NOT NULL,
    bank_id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone,
    id integer NOT NULL,
    active boolean NOT NULL
);


--
-- Name: branches_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.branches_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: branches_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.branches_id_seq OWNED BY public.branches.id;


--
-- Name: id_fa_mappings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.id_fa_mappings (
    id_value character varying NOT NULL,
    fa_value character varying NOT NULL,
    name character varying,
    phone character varying,
    additional_info json,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone,
    id integer NOT NULL,
    active boolean NOT NULL
);


--
-- Name: id_fa_mappings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.id_fa_mappings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: id_fa_mappings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.id_fa_mappings_id_seq OWNED BY public.id_fa_mappings.id;


--
-- Name: strategy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.strategy (
    description character varying,
    strategy_type character varying(10) NOT NULL,
    construct_strategy character varying NOT NULL,
    deconstruct_strategy character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone,
    id integer NOT NULL,
    active boolean NOT NULL
);


--
-- Name: strategy_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.strategy_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: strategy_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.strategy_id_seq OWNED BY public.strategy.id;


--
-- Name: wallet_service_providers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wallet_service_providers (
    sp_mnemonic character varying(50) NOT NULL,
    sp_name character varying(255) NOT NULL,
    sp_code character varying(50) NOT NULL,
    wallet_type character varying(50) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone,
    id integer NOT NULL,
    active boolean NOT NULL
);


--
-- Name: wallet_service_providers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.wallet_service_providers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: wallet_service_providers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.wallet_service_providers_id_seq OWNED BY public.wallet_service_providers.id;


--
-- Name: banks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.banks ALTER COLUMN id SET DEFAULT nextval('public.banks_id_seq'::regclass);


--
-- Name: branches id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.branches ALTER COLUMN id SET DEFAULT nextval('public.branches_id_seq'::regclass);


--
-- Name: id_fa_mappings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.id_fa_mappings ALTER COLUMN id SET DEFAULT nextval('public.id_fa_mappings_id_seq'::regclass);


--
-- Name: strategy id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy ALTER COLUMN id SET DEFAULT nextval('public.strategy_id_seq'::regclass);


--
-- Name: wallet_service_providers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wallet_service_providers ALTER COLUMN id SET DEFAULT nextval('public.wallet_service_providers_id_seq'::regclass);


--
-- Name: banks banks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.banks
    ADD CONSTRAINT banks_pkey PRIMARY KEY (id);


--
-- Name: branches branches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.branches
    ADD CONSTRAINT branches_pkey PRIMARY KEY (id);


--
-- Name: id_fa_mappings id_fa_mappings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.id_fa_mappings
    ADD CONSTRAINT id_fa_mappings_pkey PRIMARY KEY (id);


--
-- Name: strategy strategy_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy
    ADD CONSTRAINT strategy_pkey PRIMARY KEY (id);


--
-- Name: wallet_service_providers wallet_service_providers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wallet_service_providers
    ADD CONSTRAINT wallet_service_providers_pkey PRIMARY KEY (id);


--
-- Name: ix_banks_bank_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_banks_bank_code ON public.banks USING btree (bank_code);


--
-- Name: ix_banks_bank_mnemonic; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_banks_bank_mnemonic ON public.banks USING btree (bank_mnemonic);


--
-- Name: ix_branches_bank_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_branches_bank_id ON public.branches USING btree (bank_id);


--
-- Name: ix_branches_branch_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_branches_branch_code ON public.branches USING btree (branch_code);


--
-- Name: ix_branches_branch_mnemonic; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_branches_branch_mnemonic ON public.branches USING btree (branch_mnemonic);


--
-- Name: ix_id_fa_mappings_fa_value; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_id_fa_mappings_fa_value ON public.id_fa_mappings USING btree (fa_value);


--
-- Name: ix_id_fa_mappings_id_value; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_id_fa_mappings_id_value ON public.id_fa_mappings USING btree (id_value);


--
-- Name: ix_wallet_service_providers_sp_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wallet_service_providers_sp_code ON public.wallet_service_providers USING btree (sp_code);


--
-- Name: ix_wallet_service_providers_sp_mnemonic; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_wallet_service_providers_sp_mnemonic ON public.wallet_service_providers USING btree (sp_mnemonic);


--
-- Name: ix_wallet_service_providers_wallet_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wallet_service_providers_wallet_type ON public.wallet_service_providers USING btree (wallet_type);


--
-- PostgreSQL database dump complete
--

