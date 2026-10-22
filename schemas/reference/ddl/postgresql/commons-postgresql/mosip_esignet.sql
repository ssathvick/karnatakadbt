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
-- Name: esignet; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA esignet;


SET default_table_access_method = heap;

--
-- Name: client_detail; Type: TABLE; Schema: esignet; Owner: -
--

CREATE TABLE esignet.client_detail (
    id character varying(100) NOT NULL,
    name character varying(256) NOT NULL,
    rp_id character varying(100) NOT NULL,
    logo_uri character varying(2048) NOT NULL,
    redirect_uris character varying NOT NULL,
    claims character varying NOT NULL,
    acr_values character varying NOT NULL,
    public_key character varying NOT NULL,
    grant_types character varying NOT NULL,
    auth_methods character varying NOT NULL,
    status character varying(20) NOT NULL,
    cr_dtimes timestamp without time zone NOT NULL,
    upd_dtimes timestamp without time zone
);


--
-- Name: TABLE client_detail; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON TABLE esignet.client_detail IS 'Contains key alias and  metadata of all the keys used in MOSIP system.';


--
-- Name: COLUMN client_detail.id; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.client_detail.id IS 'Client ID: Unique id assigned to registered OIDC client.';


--
-- Name: COLUMN client_detail.name; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.client_detail.name IS 'Client Name: Registered name of OIDC client.';


--
-- Name: COLUMN client_detail.rp_id; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.client_detail.rp_id IS 'relying Party Id: Id of the relying Party who has created this OIDC client.';


--
-- Name: COLUMN client_detail.logo_uri; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.client_detail.logo_uri IS 'Client Logo URL: Client logo to be displayed on IDP UI.';


--
-- Name: COLUMN client_detail.redirect_uris; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.client_detail.redirect_uris IS 'Recirect URLS: Comma separated client redirect URLs.';


--
-- Name: COLUMN client_detail.claims; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.client_detail.claims IS 'Requested Claims: claims json as per policy defined for relying party, comma separated string.';


--
-- Name: COLUMN client_detail.acr_values; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.client_detail.acr_values IS 'Allowed Authentication context References(acr), comma separated string.';


--
-- Name: COLUMN client_detail.public_key; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.client_detail.public_key IS 'Public key: JWK format.';


--
-- Name: COLUMN client_detail.grant_types; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.client_detail.grant_types IS 'Grant Types: Allowed grant types for the client, comma separated string.';


--
-- Name: COLUMN client_detail.auth_methods; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.client_detail.auth_methods IS 'Client Auth methods: Allowed token endpoint authentication methods, comma separated string.';


--
-- Name: COLUMN client_detail.status; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.client_detail.status IS 'Client status: Allowed values - ACTIVE / INACTIVE.';


--
-- Name: COLUMN client_detail.cr_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.client_detail.cr_dtimes IS 'Created DateTimestamp : Date and Timestamp when the record is created/inserted';


--
-- Name: COLUMN client_detail.upd_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.client_detail.upd_dtimes IS 'Updated DateTimestamp : Date and Timestamp when any of the fields in the record is updated with new values.';


--
-- Name: consent_detail; Type: TABLE; Schema: esignet; Owner: -
--

CREATE TABLE esignet.consent_detail (
    id uuid NOT NULL,
    client_id character varying NOT NULL,
    psu_token character varying NOT NULL,
    claims character varying NOT NULL,
    authorization_scopes character varying NOT NULL,
    cr_dtimes timestamp without time zone DEFAULT now() NOT NULL,
    expire_dtimes timestamp without time zone,
    signature character varying,
    hash character varying,
    accepted_claims character varying,
    permitted_scopes character varying
);


--
-- Name: TABLE consent_detail; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON TABLE esignet.consent_detail IS 'Contains user consent details';


--
-- Name: COLUMN consent_detail.id; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_detail.id IS 'UUID : Unique id associated with each consent';


--
-- Name: COLUMN consent_detail.client_id; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_detail.client_id IS 'Client_id: associated with relying party';


--
-- Name: COLUMN consent_detail.psu_token; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_detail.psu_token IS 'PSU token associated with user consent';


--
-- Name: COLUMN consent_detail.claims; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_detail.claims IS 'Json of requested and user accepted claims';


--
-- Name: COLUMN consent_detail.authorization_scopes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_detail.authorization_scopes IS 'Json string of requested authorization scope';


--
-- Name: COLUMN consent_detail.cr_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_detail.cr_dtimes IS 'Consent creation date';


--
-- Name: COLUMN consent_detail.expire_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_detail.expire_dtimes IS 'Expiration date';


--
-- Name: COLUMN consent_detail.signature; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_detail.signature IS 'Signature of consent object ';


--
-- Name: COLUMN consent_detail.hash; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_detail.hash IS 'hash of consent object';


--
-- Name: COLUMN consent_detail.accepted_claims; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_detail.accepted_claims IS 'Accepted Claims by the user';


--
-- Name: COLUMN consent_detail.permitted_scopes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_detail.permitted_scopes IS 'Accepted Scopes by the user';


--
-- Name: consent_history; Type: TABLE; Schema: esignet; Owner: -
--

CREATE TABLE esignet.consent_history (
    id uuid NOT NULL,
    client_id character varying NOT NULL,
    psu_token character varying NOT NULL,
    claims character varying NOT NULL,
    authorization_scopes character varying NOT NULL,
    cr_dtimes timestamp without time zone DEFAULT now() NOT NULL,
    expire_dtimes timestamp without time zone,
    signature character varying,
    hash character varying,
    accepted_claims character varying,
    permitted_scopes character varying
);


--
-- Name: TABLE consent_history; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON TABLE esignet.consent_history IS 'Contains user consent details';


--
-- Name: COLUMN consent_history.id; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_history.id IS 'UUID : Unique id associated with each consent';


--
-- Name: COLUMN consent_history.client_id; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_history.client_id IS 'Client_id: associated with relying party';


--
-- Name: COLUMN consent_history.psu_token; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_history.psu_token IS 'PSU token associated with user consent';


--
-- Name: COLUMN consent_history.claims; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_history.claims IS 'Json of requested and user accepted claims';


--
-- Name: COLUMN consent_history.authorization_scopes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_history.authorization_scopes IS 'Json string of requested authorization scope';


--
-- Name: COLUMN consent_history.cr_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_history.cr_dtimes IS 'Consent creation date';


--
-- Name: COLUMN consent_history.expire_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_history.expire_dtimes IS 'Expiration date';


--
-- Name: COLUMN consent_history.signature; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_history.signature IS 'Signature of consent object ';


--
-- Name: COLUMN consent_history.hash; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_history.hash IS 'hash of consent object';


--
-- Name: COLUMN consent_history.accepted_claims; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_history.accepted_claims IS 'Accepted Claims by the user';


--
-- Name: COLUMN consent_history.permitted_scopes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.consent_history.permitted_scopes IS 'Accepted Scopes by the user';


--
-- Name: key_alias; Type: TABLE; Schema: esignet; Owner: -
--

CREATE TABLE esignet.key_alias (
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
-- Name: TABLE key_alias; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON TABLE esignet.key_alias IS 'Contains key alias and  metadata of all the keys used in MOSIP system.';


--
-- Name: COLUMN key_alias.id; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_alias.id IS 'Unique identifier (UUID) used for referencing keys in key_store table and HSM';


--
-- Name: COLUMN key_alias.app_id; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_alias.app_id IS 'To reference a Module key';


--
-- Name: COLUMN key_alias.ref_id; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_alias.ref_id IS 'To reference a Encryption key ';


--
-- Name: COLUMN key_alias.key_gen_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_alias.key_gen_dtimes IS 'Date and time when the key was generated.';


--
-- Name: COLUMN key_alias.key_expire_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_alias.key_expire_dtimes IS 'Date and time when the key will be expired. This will be derived based on the configuration / policy defined in Key policy definition.';


--
-- Name: COLUMN key_alias.status_code; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_alias.status_code IS 'Status of the key, whether it is active or expired.';


--
-- Name: COLUMN key_alias.lang_code; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_alias.lang_code IS 'For multilanguage implementation this attribute Refers master.language.code. The value of some of the attributes in current record is stored in this respective language. ';


--
-- Name: COLUMN key_alias.cr_by; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_alias.cr_by IS 'ID or name of the user who create / insert record';


--
-- Name: COLUMN key_alias.cr_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_alias.cr_dtimes IS 'Date and Timestamp when the record is created/inserted';


--
-- Name: COLUMN key_alias.upd_by; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_alias.upd_by IS 'ID or name of the user who update the record with new values';


--
-- Name: COLUMN key_alias.upd_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_alias.upd_dtimes IS 'Date and Timestamp when any of the fields in the record is updated with new values.';


--
-- Name: COLUMN key_alias.is_deleted; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_alias.is_deleted IS 'Flag to mark whether the record is Soft deleted.';


--
-- Name: COLUMN key_alias.del_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_alias.del_dtimes IS 'Date and Timestamp when the record is soft deleted with is_deleted=TRUE';


--
-- Name: key_policy_def; Type: TABLE; Schema: esignet; Owner: -
--

CREATE TABLE esignet.key_policy_def (
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
-- Name: TABLE key_policy_def; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON TABLE esignet.key_policy_def IS 'Key Policy Defination: Policy related to encryption key management is defined here. For eg. Expiry duration of a key generated.';


--
-- Name: COLUMN key_policy_def.app_id; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_policy_def.app_id IS 'Application ID: Application id for which the key policy is defined';


--
-- Name: COLUMN key_policy_def.key_validity_duration; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_policy_def.key_validity_duration IS 'Key Validity Duration: Duration for which key is valid';


--
-- Name: COLUMN key_policy_def.is_active; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_policy_def.is_active IS 'IS_Active : Flag to mark whether the record is Active or In-active';


--
-- Name: COLUMN key_policy_def.cr_by; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_policy_def.cr_by IS 'Created By : ID or name of the user who create / insert record';


--
-- Name: COLUMN key_policy_def.cr_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_policy_def.cr_dtimes IS 'Created DateTimestamp : Date and Timestamp when the record is created/inserted';


--
-- Name: COLUMN key_policy_def.upd_by; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_policy_def.upd_by IS 'Updated By : ID or name of the user who update the record with new values';


--
-- Name: COLUMN key_policy_def.upd_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_policy_def.upd_dtimes IS 'Updated DateTimestamp : Date and Timestamp when any of the fields in the record is updated with new values.';


--
-- Name: COLUMN key_policy_def.is_deleted; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_policy_def.is_deleted IS 'IS_Deleted : Flag to mark whether the record is Soft deleted.';


--
-- Name: COLUMN key_policy_def.del_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_policy_def.del_dtimes IS 'Deleted DateTimestamp : Date and Timestamp when the record is soft deleted with is_deleted=TRUE';


--
-- Name: key_store; Type: TABLE; Schema: esignet; Owner: -
--

CREATE TABLE esignet.key_store (
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
-- Name: TABLE key_store; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON TABLE esignet.key_store IS 'Stores Encryption (Base) private keys along with certificates';


--
-- Name: COLUMN key_store.id; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_store.id IS 'Unique identifier (UUID) for referencing keys';


--
-- Name: COLUMN key_store.master_key; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_store.master_key IS 'UUID of the master key used to encrypt this key';


--
-- Name: COLUMN key_store.private_key; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_store.private_key IS 'Encrypted private key';


--
-- Name: COLUMN key_store.certificate_data; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_store.certificate_data IS 'X.509 encoded certificate data';


--
-- Name: COLUMN key_store.cr_by; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_store.cr_by IS 'ID or name of the user who create / insert record';


--
-- Name: COLUMN key_store.cr_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_store.cr_dtimes IS 'Date and Timestamp when the record is created/inserted';


--
-- Name: COLUMN key_store.upd_by; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_store.upd_by IS 'ID or name of the user who update the record with new values';


--
-- Name: COLUMN key_store.upd_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_store.upd_dtimes IS 'Date and Timestamp when any of the fields in the record is updated with new values.';


--
-- Name: COLUMN key_store.is_deleted; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_store.is_deleted IS 'Flag to mark whether the record is Soft deleted.';


--
-- Name: COLUMN key_store.del_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.key_store.del_dtimes IS 'Date and Timestamp when the record is soft deleted with is_deleted=TRUE';


--
-- Name: public_key_registry; Type: TABLE; Schema: esignet; Owner: -
--

CREATE TABLE esignet.public_key_registry (
    id_hash character varying(100) NOT NULL,
    auth_factor character varying(25) NOT NULL,
    psu_token character varying(256) NOT NULL,
    public_key character varying NOT NULL,
    expire_dtimes timestamp without time zone NOT NULL,
    wallet_binding_id character varying(256) NOT NULL,
    public_key_hash character varying(100) NOT NULL,
    certificate character varying NOT NULL,
    cr_dtimes timestamp without time zone NOT NULL,
    thumbprint character varying NOT NULL
);


--
-- Name: TABLE public_key_registry; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON TABLE esignet.public_key_registry IS 'Contains id_hash and their respective PSU Tokens,public keys and wallet binding ids.';


--
-- Name: COLUMN public_key_registry.id_hash; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.public_key_registry.id_hash IS 'Contains Id hash.';


--
-- Name: COLUMN public_key_registry.auth_factor; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.public_key_registry.auth_factor IS 'Supported auth factor type.';


--
-- Name: COLUMN public_key_registry.psu_token; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.public_key_registry.psu_token IS 'PSU Token: Partner Specific User Token.';


--
-- Name: COLUMN public_key_registry.public_key; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.public_key_registry.public_key IS 'Public Key: Used to validate JWT signature and encrypt Wallet Binding Id.';


--
-- Name: COLUMN public_key_registry.expire_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.public_key_registry.expire_dtimes IS 'Expiry DateTimestamp : Date and Timestamp of the expiry of the binding entry.';


--
-- Name: COLUMN public_key_registry.wallet_binding_id; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.public_key_registry.wallet_binding_id IS 'Wallet Binding Id: hash of PSU  Token and salt.';


--
-- Name: COLUMN public_key_registry.public_key_hash; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.public_key_registry.public_key_hash IS 'Public Key Hash: Hash of  Public Key.';


--
-- Name: COLUMN public_key_registry.certificate; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.public_key_registry.certificate IS 'Signed certificate';


--
-- Name: COLUMN public_key_registry.cr_dtimes; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.public_key_registry.cr_dtimes IS 'Created DateTimestamp : Date and Timestamp when the record is created/inserted.';


--
-- Name: COLUMN public_key_registry.thumbprint; Type: COMMENT; Schema: esignet; Owner: -
--

COMMENT ON COLUMN esignet.public_key_registry.thumbprint IS 'Thumbprint generated from the certificate';


--
-- Name: consent_detail consent_detail_pkey; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.consent_detail
    ADD CONSTRAINT consent_detail_pkey PRIMARY KEY (id);


--
-- Name: consent_history consent_history_pkey; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.consent_history
    ADD CONSTRAINT consent_history_pkey PRIMARY KEY (id);


--
-- Name: client_detail pk_clntdtl_id; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.client_detail
    ADD CONSTRAINT pk_clntdtl_id PRIMARY KEY (id);


--
-- Name: key_alias pk_keymals_id; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.key_alias
    ADD CONSTRAINT pk_keymals_id PRIMARY KEY (id);


--
-- Name: key_policy_def pk_keypdef_id; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.key_policy_def
    ADD CONSTRAINT pk_keypdef_id PRIMARY KEY (app_id);


--
-- Name: key_store pk_keystr_id; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.key_store
    ADD CONSTRAINT pk_keystr_id PRIMARY KEY (id);


--
-- Name: public_key_registry pk_public_key_registry; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.public_key_registry
    ADD CONSTRAINT pk_public_key_registry PRIMARY KEY (id_hash, auth_factor);


--
-- Name: client_detail uk_clntdtl_key; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.client_detail
    ADD CONSTRAINT uk_clntdtl_key UNIQUE (public_key);


--
-- Name: key_alias uni_ident_const; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.key_alias
    ADD CONSTRAINT uni_ident_const UNIQUE (uni_ident);


--
-- Name: consent_detail unique_client_token; Type: CONSTRAINT; Schema: esignet; Owner: -
--

ALTER TABLE ONLY esignet.consent_detail
    ADD CONSTRAINT unique_client_token UNIQUE (client_id, psu_token);


--
-- Name: idx_consent_history_psu_client; Type: INDEX; Schema: esignet; Owner: -
--

CREATE INDEX idx_consent_history_psu_client ON esignet.consent_history USING btree (psu_token, client_id);


--
-- Name: idx_consent_psu_client; Type: INDEX; Schema: esignet; Owner: -
--

CREATE INDEX idx_consent_psu_client ON esignet.consent_detail USING btree (psu_token, client_id);


--
-- PostgreSQL database dump complete
--

