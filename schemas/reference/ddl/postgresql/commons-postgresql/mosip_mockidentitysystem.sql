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
-- Name: mockidentitysystem; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA mockidentitysystem;


SET default_table_access_method = heap;

--
-- Name: key_alias; Type: TABLE; Schema: mockidentitysystem; Owner: -
--

CREATE TABLE mockidentitysystem.key_alias (
    id character varying(36) NOT NULL,
    app_id character varying(36) NOT NULL,
    ref_id character varying(128),
    key_gen_dtimes timestamp without time zone,
    key_expire_dtimes timestamp without time zone,
    status_code character varying(36),
    lang_code character varying(3),
    cr_by character varying(256) NOT NULL,
    cr_dtimes timestamp without time zone NOT NULL,
    upd_by character varying(256),
    upd_dtimes timestamp without time zone,
    is_deleted boolean DEFAULT false,
    del_dtimes timestamp without time zone,
    cert_thumbprint character varying(100),
    uni_ident character varying(50)
);


--
-- Name: TABLE key_alias; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON TABLE mockidentitysystem.key_alias IS 'Contains key alias and  metadata of all the keys used in MOSIP system.';


--
-- Name: COLUMN key_alias.id; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_alias.id IS 'Unique identifier (UUID) used for referencing keys in key_store table and HSM';


--
-- Name: COLUMN key_alias.app_id; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_alias.app_id IS 'To reference a Module key';


--
-- Name: COLUMN key_alias.ref_id; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_alias.ref_id IS 'To reference a Encryption key ';


--
-- Name: COLUMN key_alias.key_gen_dtimes; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_alias.key_gen_dtimes IS 'Date and time when the key was generated.';


--
-- Name: COLUMN key_alias.key_expire_dtimes; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_alias.key_expire_dtimes IS 'Date and time when the key will be expired. This will be derived based on the configuration / policy defined in Key policy definition.';


--
-- Name: COLUMN key_alias.status_code; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_alias.status_code IS 'Status of the key, whether it is active or expired.';


--
-- Name: COLUMN key_alias.lang_code; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_alias.lang_code IS 'For multilanguage implementation this attribute Refers master.language.code. The value of some of the attributes in current record is stored in this respective language. ';


--
-- Name: COLUMN key_alias.cr_by; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_alias.cr_by IS 'ID or name of the user who create / insert record';


--
-- Name: COLUMN key_alias.cr_dtimes; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_alias.cr_dtimes IS 'Date and Timestamp when the record is created/inserted';


--
-- Name: COLUMN key_alias.upd_by; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_alias.upd_by IS 'ID or name of the user who update the record with new values';


--
-- Name: COLUMN key_alias.upd_dtimes; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_alias.upd_dtimes IS 'Date and Timestamp when any of the fields in the record is updated with new values.';


--
-- Name: COLUMN key_alias.is_deleted; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_alias.is_deleted IS 'Flag to mark whether the record is Soft deleted.';


--
-- Name: COLUMN key_alias.del_dtimes; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_alias.del_dtimes IS 'Date and Timestamp when the record is soft deleted with is_deleted=TRUE';


--
-- Name: key_policy_def; Type: TABLE; Schema: mockidentitysystem; Owner: -
--

CREATE TABLE mockidentitysystem.key_policy_def (
    app_id character varying(36) NOT NULL,
    key_validity_duration smallint,
    is_active boolean NOT NULL,
    pre_expire_days smallint,
    access_allowed character varying(1024),
    cr_by character varying(256) NOT NULL,
    cr_dtimes timestamp without time zone NOT NULL,
    upd_by character varying(256),
    upd_dtimes timestamp without time zone,
    is_deleted boolean DEFAULT false,
    del_dtimes timestamp without time zone
);


--
-- Name: TABLE key_policy_def; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON TABLE mockidentitysystem.key_policy_def IS 'Key Policy Defination: Policy related to encryption key management is defined here. For eg. Expiry duration of a key generated.';


--
-- Name: COLUMN key_policy_def.app_id; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_policy_def.app_id IS 'Application ID: Application id for which the key policy is defined';


--
-- Name: COLUMN key_policy_def.key_validity_duration; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_policy_def.key_validity_duration IS 'Key Validity Duration: Duration for which key is valid';


--
-- Name: COLUMN key_policy_def.is_active; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_policy_def.is_active IS 'IS_Active : Flag to mark whether the record is Active or In-active';


--
-- Name: COLUMN key_policy_def.cr_by; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_policy_def.cr_by IS 'Created By : ID or name of the user who create / insert record';


--
-- Name: COLUMN key_policy_def.cr_dtimes; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_policy_def.cr_dtimes IS 'Created DateTimestamp : Date and Timestamp when the record is created/inserted';


--
-- Name: COLUMN key_policy_def.upd_by; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_policy_def.upd_by IS 'Updated By : ID or name of the user who update the record with new values';


--
-- Name: COLUMN key_policy_def.upd_dtimes; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_policy_def.upd_dtimes IS 'Updated DateTimestamp : Date and Timestamp when any of the fields in the record is updated with new values.';


--
-- Name: COLUMN key_policy_def.is_deleted; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_policy_def.is_deleted IS 'IS_Deleted : Flag to mark whether the record is Soft deleted.';


--
-- Name: COLUMN key_policy_def.del_dtimes; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_policy_def.del_dtimes IS 'Deleted DateTimestamp : Date and Timestamp when the record is soft deleted with is_deleted=TRUE';


--
-- Name: key_store; Type: TABLE; Schema: mockidentitysystem; Owner: -
--

CREATE TABLE mockidentitysystem.key_store (
    id character varying(36) NOT NULL,
    master_key character varying(36) NOT NULL,
    private_key character varying(2500) NOT NULL,
    certificate_data character varying NOT NULL,
    cr_by character varying(256) NOT NULL,
    cr_dtimes timestamp without time zone NOT NULL,
    upd_by character varying(256),
    upd_dtimes timestamp without time zone,
    is_deleted boolean DEFAULT false,
    del_dtimes timestamp without time zone
);


--
-- Name: TABLE key_store; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON TABLE mockidentitysystem.key_store IS 'Stores Encryption (Base) private keys along with certificates';


--
-- Name: COLUMN key_store.id; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_store.id IS 'Unique identifier (UUID) for referencing keys';


--
-- Name: COLUMN key_store.master_key; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_store.master_key IS 'UUID of the master key used to encrypt this key';


--
-- Name: COLUMN key_store.private_key; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_store.private_key IS 'Encrypted private key';


--
-- Name: COLUMN key_store.certificate_data; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_store.certificate_data IS 'X.509 encoded certificate data';


--
-- Name: COLUMN key_store.cr_by; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_store.cr_by IS 'ID or name of the user who create / insert record';


--
-- Name: COLUMN key_store.cr_dtimes; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_store.cr_dtimes IS 'Date and Timestamp when the record is created/inserted';


--
-- Name: COLUMN key_store.upd_by; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_store.upd_by IS 'ID or name of the user who update the record with new values';


--
-- Name: COLUMN key_store.upd_dtimes; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_store.upd_dtimes IS 'Date and Timestamp when any of the fields in the record is updated with new values.';


--
-- Name: COLUMN key_store.is_deleted; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_store.is_deleted IS 'Flag to mark whether the record is Soft deleted.';


--
-- Name: COLUMN key_store.del_dtimes; Type: COMMENT; Schema: mockidentitysystem; Owner: -
--

COMMENT ON COLUMN mockidentitysystem.key_store.del_dtimes IS 'Date and Timestamp when the record is soft deleted with is_deleted=TRUE';


--
-- Name: kyc_auth; Type: TABLE; Schema: mockidentitysystem; Owner: -
--

CREATE TABLE mockidentitysystem.kyc_auth (
    kyc_token character varying(255),
    individual_id character varying(255),
    partner_specific_user_token character varying(255),
    response_time timestamp without time zone,
    transaction_id character varying(255),
    validity integer
);


--
-- Name: mock_identity; Type: TABLE; Schema: mockidentitysystem; Owner: -
--

CREATE TABLE mockidentitysystem.mock_identity (
    individual_id character varying(36) NOT NULL,
    identity_json character varying NOT NULL
);


--
-- Name: key_alias pk_keymals_id; Type: CONSTRAINT; Schema: mockidentitysystem; Owner: -
--

ALTER TABLE ONLY mockidentitysystem.key_alias
    ADD CONSTRAINT pk_keymals_id PRIMARY KEY (id);


--
-- Name: key_policy_def pk_keypdef_id; Type: CONSTRAINT; Schema: mockidentitysystem; Owner: -
--

ALTER TABLE ONLY mockidentitysystem.key_policy_def
    ADD CONSTRAINT pk_keypdef_id PRIMARY KEY (app_id);


--
-- Name: key_store pk_keystr_id; Type: CONSTRAINT; Schema: mockidentitysystem; Owner: -
--

ALTER TABLE ONLY mockidentitysystem.key_store
    ADD CONSTRAINT pk_keystr_id PRIMARY KEY (id);


--
-- Name: mock_identity pk_mock_id_code; Type: CONSTRAINT; Schema: mockidentitysystem; Owner: -
--

ALTER TABLE ONLY mockidentitysystem.mock_identity
    ADD CONSTRAINT pk_mock_id_code PRIMARY KEY (individual_id);


--
-- Name: key_alias uni_ident_const; Type: CONSTRAINT; Schema: mockidentitysystem; Owner: -
--

ALTER TABLE ONLY mockidentitysystem.key_alias
    ADD CONSTRAINT uni_ident_const UNIQUE (uni_ident);


--
-- PostgreSQL database dump complete
--

