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

-- *not* creating schema, since initdb creates it


--
-- Name: accountstatementstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.accountstatementstatus AS ENUM (
    'NOT_APPLICABLE',
    'PENDING',
    'PROCESSING',
    'SUCCESS',
    'FAILED'
);


--
-- Name: debitcredittypes; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.debitcredittypes AS ENUM (
    'DEBIT',
    'CREDIT'
);


--
-- Name: paymentstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.paymentstatus AS ENUM (
    'NOT_APPLICABLE',
    'PENDING',
    'PROCESSING',
    'SUCCESS',
    'FAILED'
);


SET default_table_access_method = heap;

--
-- Name: account_statements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.account_statements (
    account_number character varying NOT NULL,
    account_statement_lob text,
    account_statement_generation_status public.accountstatementstatus NOT NULL,
    account_statement_date timestamp without time zone NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone,
    id integer NOT NULL,
    active boolean NOT NULL
);


--
-- Name: account_statements_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.account_statements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: account_statements_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.account_statements_id_seq OWNED BY public.account_statements.id;


--
-- Name: accounting_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.accounting_logs (
    reference_no character varying NOT NULL,
    corresponding_block_reference_no character varying,
    customer_reference_no character varying NOT NULL,
    debit_credit public.debitcredittypes NOT NULL,
    account_number character varying NOT NULL,
    transaction_amount double precision NOT NULL,
    transaction_date timestamp without time zone NOT NULL,
    transaction_currency character varying NOT NULL,
    transaction_code character varying,
    narrative_1 character varying,
    narrative_2 character varying,
    narrative_3 character varying,
    narrative_4 character varying,
    narrative_5 character varying,
    narrative_6 character varying,
    reported_in_mt940 boolean NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone,
    id integer NOT NULL,
    active boolean NOT NULL
);


--
-- Name: accounting_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.accounting_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: accounting_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.accounting_logs_id_seq OWNED BY public.accounting_logs.id;


--
-- Name: accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.accounts (
    account_holder_name character varying NOT NULL,
    account_number character varying NOT NULL,
    account_currency character varying NOT NULL,
    account_holder_phone character varying NOT NULL,
    account_holder_email character varying NOT NULL,
    book_balance double precision NOT NULL,
    available_balance double precision NOT NULL,
    blocked_amount double precision NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone,
    id integer NOT NULL,
    active boolean NOT NULL
);


--
-- Name: accounts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.accounts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: accounts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.accounts_id_seq OWNED BY public.accounts.id;


--
-- Name: fund_blocks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fund_blocks (
    block_reference_no character varying NOT NULL,
    account_number character varying NOT NULL,
    currency character varying NOT NULL,
    amount double precision NOT NULL,
    amount_released double precision NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone,
    id integer NOT NULL,
    active boolean NOT NULL
);


--
-- Name: fund_blocks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fund_blocks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fund_blocks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fund_blocks_id_seq OWNED BY public.fund_blocks.id;


--
-- Name: initiate_payment_batch_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.initiate_payment_batch_requests (
    batch_id character varying NOT NULL,
    payment_initiate_attempts integer NOT NULL,
    initiate_payment_payloads json NOT NULL,
    payment_status public.paymentstatus NOT NULL,
    batching_request_status public.paymentstatus NOT NULL,
    batching_request_latest_error_code character varying,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone,
    id integer NOT NULL,
    active boolean NOT NULL
);


--
-- Name: initiate_payment_batch_requests_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.initiate_payment_batch_requests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: initiate_payment_batch_requests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.initiate_payment_batch_requests_id_seq OWNED BY public.initiate_payment_batch_requests.id;


--
-- Name: initiate_payment_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.initiate_payment_requests (
    batch_id character varying NOT NULL,
    payment_reference_number character varying,
    remitting_account character varying NOT NULL,
    remitting_account_currency character varying NOT NULL,
    payment_amount double precision NOT NULL,
    payment_date character varying NOT NULL,
    funds_blocked_reference_number character varying NOT NULL,
    beneficiary_name character varying NOT NULL,
    beneficiary_account character varying NOT NULL,
    beneficiary_account_currency character varying NOT NULL,
    beneficiary_account_type character varying NOT NULL,
    beneficiary_bank_code character varying NOT NULL,
    beneficiary_branch_code character varying NOT NULL,
    beneficiary_mobile_wallet_provider character varying,
    beneficiary_phone_no character varying,
    beneficiary_email character varying,
    beneficiary_email_wallet_provider character varying,
    narrative_1 character varying,
    narrative_2 character varying,
    narrative_3 character varying,
    narrative_4 character varying,
    narrative_5 character varying,
    narrative_6 character varying,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone,
    id integer NOT NULL,
    active boolean NOT NULL
);


--
-- Name: initiate_payment_requests_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.initiate_payment_requests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: initiate_payment_requests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.initiate_payment_requests_id_seq OWNED BY public.initiate_payment_requests.id;


--
-- Name: account_statements id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_statements ALTER COLUMN id SET DEFAULT nextval('public.account_statements_id_seq'::regclass);


--
-- Name: accounting_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounting_logs ALTER COLUMN id SET DEFAULT nextval('public.accounting_logs_id_seq'::regclass);


--
-- Name: accounts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts ALTER COLUMN id SET DEFAULT nextval('public.accounts_id_seq'::regclass);


--
-- Name: fund_blocks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fund_blocks ALTER COLUMN id SET DEFAULT nextval('public.fund_blocks_id_seq'::regclass);


--
-- Name: initiate_payment_batch_requests id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.initiate_payment_batch_requests ALTER COLUMN id SET DEFAULT nextval('public.initiate_payment_batch_requests_id_seq'::regclass);


--
-- Name: initiate_payment_requests id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.initiate_payment_requests ALTER COLUMN id SET DEFAULT nextval('public.initiate_payment_requests_id_seq'::regclass);


--
-- Name: account_statements account_statements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_statements
    ADD CONSTRAINT account_statements_pkey PRIMARY KEY (id);


--
-- Name: accounting_logs accounting_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounting_logs
    ADD CONSTRAINT accounting_logs_pkey PRIMARY KEY (id);


--
-- Name: accounts accounts_account_holder_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_account_holder_email_key UNIQUE (account_holder_email);


--
-- Name: accounts accounts_account_holder_phone_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_account_holder_phone_key UNIQUE (account_holder_phone);


--
-- Name: accounts accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_pkey PRIMARY KEY (id);


--
-- Name: fund_blocks fund_blocks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fund_blocks
    ADD CONSTRAINT fund_blocks_pkey PRIMARY KEY (id);


--
-- Name: initiate_payment_batch_requests initiate_payment_batch_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.initiate_payment_batch_requests
    ADD CONSTRAINT initiate_payment_batch_requests_pkey PRIMARY KEY (id);


--
-- Name: initiate_payment_requests initiate_payment_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.initiate_payment_requests
    ADD CONSTRAINT initiate_payment_requests_pkey PRIMARY KEY (id);


--
-- Name: ix_account_statements_account_number; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_account_statements_account_number ON public.account_statements USING btree (account_number);


--
-- Name: ix_accounting_logs_account_number; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_accounting_logs_account_number ON public.accounting_logs USING btree (account_number);


--
-- Name: ix_accounting_logs_customer_reference_no; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_accounting_logs_customer_reference_no ON public.accounting_logs USING btree (customer_reference_no);


--
-- Name: ix_accounting_logs_reference_no; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_accounting_logs_reference_no ON public.accounting_logs USING btree (reference_no);


--
-- Name: ix_fund_blocks_block_reference_no; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_fund_blocks_block_reference_no ON public.fund_blocks USING btree (block_reference_no);


--
-- Name: ix_initiate_payment_batch_requests_batch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_initiate_payment_batch_requests_batch_id ON public.initiate_payment_batch_requests USING btree (batch_id);


--
-- Name: ix_initiate_payment_requests_batch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_initiate_payment_requests_batch_id ON public.initiate_payment_requests USING btree (batch_id);


--
-- Name: ix_initiate_payment_requests_payment_reference_number; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_initiate_payment_requests_payment_reference_number ON public.initiate_payment_requests USING btree (payment_reference_number);


--
-- PostgreSQL database dump complete
--

