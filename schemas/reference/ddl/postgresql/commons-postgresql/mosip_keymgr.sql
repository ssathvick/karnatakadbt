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
-- Name: keymgr; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA keymgr;


SET default_table_access_method = heap;

--
-- Name: ca_cert_store; Type: TABLE; Schema: keymgr; Owner: -
--

CREATE TABLE keymgr.ca_cert_store (
    cert_id character varying(36) NOT NULL,
    cert_subject character varying(500) NOT NULL,
    cert_issuer character varying(500) NOT NULL,
    issuer_id character varying(36) NOT NULL,
    cert_not_before timestamp without time zone,
    cert_not_after timestamp without time zone,
    crl_uri character varying(120),
    cert_data character varying,
    cert_thumbprint character varying(100),
    cert_serial_no character varying(50),
    partner_domain character varying(36),
    cr_by character varying(256),
    cr_dtimes timestamp without time zone,
    upd_by character varying(256),
    upd_dtimes timestamp without time zone,
    is_deleted boolean DEFAULT false,
    del_dtimes timestamp without time zone
);


--
-- Name: TABLE ca_cert_store; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON TABLE keymgr.ca_cert_store IS 'Certificate Authority Certificate Store: Store details of all the certificate provided by certificate authority which will be used by MOSIP';


--
-- Name: COLUMN ca_cert_store.cert_id; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.ca_cert_store.cert_id IS 'Certificate ID: Unique ID (UUID) will be generated and assigned to the uploaded CA/Sub-CA certificate';


--
-- Name: COLUMN ca_cert_store.cert_subject; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.ca_cert_store.cert_subject IS 'Certificate Subject: Subject DN of the certificate';


--
-- Name: COLUMN ca_cert_store.cert_issuer; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.ca_cert_store.cert_issuer IS 'Certificate Issuer: Issuer DN of the certificate';


--
-- Name: COLUMN ca_cert_store.issuer_id; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.ca_cert_store.issuer_id IS 'Issuer UUID of the certificate. (Issuer certificate should be available in the DB)';


--
-- Name: COLUMN ca_cert_store.cert_not_before; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.ca_cert_store.cert_not_before IS 'Certificate Start Date: Certificate Interval - Validity Start Date & Time';


--
-- Name: COLUMN ca_cert_store.cert_not_after; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.ca_cert_store.cert_not_after IS 'Certificate Validity end Date: Certificate Interval - Validity End Date & Time';


--
-- Name: COLUMN ca_cert_store.crl_uri; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.ca_cert_store.crl_uri IS 'CRL URL: CRL URI of the issuer.';


--
-- Name: COLUMN ca_cert_store.cert_data; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.ca_cert_store.cert_data IS 'Certificate Data: PEM Encoded actual certificate data.';


--
-- Name: COLUMN ca_cert_store.cert_thumbprint; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.ca_cert_store.cert_thumbprint IS 'Certificate Thumb Print: SHA1 generated certificate thumbprint.';


--
-- Name: COLUMN ca_cert_store.cert_serial_no; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.ca_cert_store.cert_serial_no IS 'Certificate Serial No: Serial Number of the certificate.';


--
-- Name: COLUMN ca_cert_store.partner_domain; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.ca_cert_store.partner_domain IS 'Partner Domain : To add Partner Domain in CA/Sub-CA certificate chain';


--
-- Name: COLUMN ca_cert_store.cr_by; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.ca_cert_store.cr_by IS 'Created By : ID or name of the user who create / insert record';


--
-- Name: COLUMN ca_cert_store.cr_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.ca_cert_store.cr_dtimes IS 'Created DateTimestamp : Date and Timestamp when the record is created/inserted';


--
-- Name: COLUMN ca_cert_store.upd_by; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.ca_cert_store.upd_by IS 'Updated By : ID or name of the user who update the record with new values';


--
-- Name: COLUMN ca_cert_store.upd_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.ca_cert_store.upd_dtimes IS 'Updated DateTimestamp : Date and Timestamp when any of the fields in the record is updated with new values.';


--
-- Name: COLUMN ca_cert_store.is_deleted; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.ca_cert_store.is_deleted IS 'IS_Deleted : Flag to mark whether the record is Soft deleted.';


--
-- Name: COLUMN ca_cert_store.del_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.ca_cert_store.del_dtimes IS 'Deleted DateTimestamp : Date and Timestamp when the record is soft deleted with is_deleted=TRUE';


--
-- Name: data_encrypt_keystore; Type: TABLE; Schema: keymgr; Owner: -
--

CREATE TABLE keymgr.data_encrypt_keystore (
    id bigint NOT NULL,
    key character varying(64) NOT NULL,
    key_status character varying(16),
    cr_by character varying(256) NOT NULL,
    cr_dtimes timestamp without time zone NOT NULL,
    upd_by character varying(256),
    upd_dtimes timestamp without time zone
);


--
-- Name: TABLE data_encrypt_keystore; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON TABLE keymgr.data_encrypt_keystore IS 'Data Encrypt Keystore: Table is used to store the encryption key aliases which is used encrypt the data stored in identity cache table store.';


--
-- Name: COLUMN data_encrypt_keystore.id; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.data_encrypt_keystore.id IS 'Id: Id of an encryption key alias';


--
-- Name: COLUMN data_encrypt_keystore.key; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.data_encrypt_keystore.key IS 'Key: Encryption key, Key which is used to encrypt the data used in identity cache tables store';


--
-- Name: COLUMN data_encrypt_keystore.key_status; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.data_encrypt_keystore.key_status IS 'Key Status: Status of the key for ex. Key is expired, active or any other state which is defined in system';


--
-- Name: COLUMN data_encrypt_keystore.cr_by; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.data_encrypt_keystore.cr_by IS 'Created By : ID or name of the user who create / insert record';


--
-- Name: COLUMN data_encrypt_keystore.cr_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.data_encrypt_keystore.cr_dtimes IS 'Created DateTimestamp : Date and Timestamp when the record is created/inserted';


--
-- Name: COLUMN data_encrypt_keystore.upd_by; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.data_encrypt_keystore.upd_by IS 'Updated By : ID or name of the user who update the record with new values';


--
-- Name: COLUMN data_encrypt_keystore.upd_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.data_encrypt_keystore.upd_dtimes IS 'Updated DateTimestamp : Date and Timestamp when any of the fields in the record is updated with new values.';


--
-- Name: key_alias; Type: TABLE; Schema: keymgr; Owner: -
--

CREATE TABLE keymgr.key_alias (
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
-- Name: TABLE key_alias; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON TABLE keymgr.key_alias IS 'Contains key alias and  metadata of all the keys used in MOSIP system.';


--
-- Name: COLUMN key_alias.id; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_alias.id IS 'Unique identifier (UUID) used for referencing keys in key_store table and HSM';


--
-- Name: COLUMN key_alias.app_id; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_alias.app_id IS 'To reference a Module key';


--
-- Name: COLUMN key_alias.ref_id; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_alias.ref_id IS 'To reference a Encryption key ';


--
-- Name: COLUMN key_alias.key_gen_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_alias.key_gen_dtimes IS 'Date and time when the key was generated.';


--
-- Name: COLUMN key_alias.key_expire_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_alias.key_expire_dtimes IS 'Date and time when the key will be expired. This will be derived based on the configuration / policy defined in Key policy definition.';


--
-- Name: COLUMN key_alias.status_code; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_alias.status_code IS 'Status of the key, whether it is active or expired.';


--
-- Name: COLUMN key_alias.lang_code; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_alias.lang_code IS 'For multilanguage implementation this attribute Refers master.language.code. The value of some of the attributes in current record is stored in this respective language. ';


--
-- Name: COLUMN key_alias.cr_by; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_alias.cr_by IS 'ID or name of the user who create / insert record';


--
-- Name: COLUMN key_alias.cr_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_alias.cr_dtimes IS 'Date and Timestamp when the record is created/inserted';


--
-- Name: COLUMN key_alias.upd_by; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_alias.upd_by IS 'ID or name of the user who update the record with new values';


--
-- Name: COLUMN key_alias.upd_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_alias.upd_dtimes IS 'Date and Timestamp when any of the fields in the record is updated with new values.';


--
-- Name: COLUMN key_alias.is_deleted; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_alias.is_deleted IS 'Flag to mark whether the record is Soft deleted.';


--
-- Name: COLUMN key_alias.del_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_alias.del_dtimes IS 'Date and Timestamp when the record is soft deleted with is_deleted=TRUE';


--
-- Name: key_policy_def; Type: TABLE; Schema: keymgr; Owner: -
--

CREATE TABLE keymgr.key_policy_def (
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
-- Name: TABLE key_policy_def; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON TABLE keymgr.key_policy_def IS 'Key Policy Defination: Policy related to encryption key management is defined here. For eg. Expiry duration of a key generated.';


--
-- Name: COLUMN key_policy_def.app_id; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_policy_def.app_id IS 'Application ID: Application id for which the key policy is defined';


--
-- Name: COLUMN key_policy_def.key_validity_duration; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_policy_def.key_validity_duration IS 'Key Validity Duration: Duration for which key is valid';


--
-- Name: COLUMN key_policy_def.is_active; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_policy_def.is_active IS 'IS_Active : Flag to mark whether the record is Active or In-active';


--
-- Name: COLUMN key_policy_def.cr_by; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_policy_def.cr_by IS 'Created By : ID or name of the user who create / insert record';


--
-- Name: COLUMN key_policy_def.cr_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_policy_def.cr_dtimes IS 'Created DateTimestamp : Date and Timestamp when the record is created/inserted';


--
-- Name: COLUMN key_policy_def.upd_by; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_policy_def.upd_by IS 'Updated By : ID or name of the user who update the record with new values';


--
-- Name: COLUMN key_policy_def.upd_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_policy_def.upd_dtimes IS 'Updated DateTimestamp : Date and Timestamp when any of the fields in the record is updated with new values.';


--
-- Name: COLUMN key_policy_def.is_deleted; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_policy_def.is_deleted IS 'IS_Deleted : Flag to mark whether the record is Soft deleted.';


--
-- Name: COLUMN key_policy_def.del_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_policy_def.del_dtimes IS 'Deleted DateTimestamp : Date and Timestamp when the record is soft deleted with is_deleted=TRUE';


--
-- Name: key_store; Type: TABLE; Schema: keymgr; Owner: -
--

CREATE TABLE keymgr.key_store (
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
-- Name: TABLE key_store; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON TABLE keymgr.key_store IS 'Stores Encryption (Base) private keys along with certificates';


--
-- Name: COLUMN key_store.id; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_store.id IS 'Unique identifier (UUID) for referencing keys';


--
-- Name: COLUMN key_store.master_key; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_store.master_key IS 'UUID of the master key used to encrypt this key';


--
-- Name: COLUMN key_store.private_key; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_store.private_key IS 'Encrypted private key';


--
-- Name: COLUMN key_store.certificate_data; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_store.certificate_data IS 'X.509 encoded certificate data';


--
-- Name: COLUMN key_store.cr_by; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_store.cr_by IS 'ID or name of the user who create / insert record';


--
-- Name: COLUMN key_store.cr_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_store.cr_dtimes IS 'Date and Timestamp when the record is created/inserted';


--
-- Name: COLUMN key_store.upd_by; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_store.upd_by IS 'ID or name of the user who update the record with new values';


--
-- Name: COLUMN key_store.upd_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_store.upd_dtimes IS 'Date and Timestamp when any of the fields in the record is updated with new values.';


--
-- Name: COLUMN key_store.is_deleted; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_store.is_deleted IS 'Flag to mark whether the record is Soft deleted.';


--
-- Name: COLUMN key_store.del_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.key_store.del_dtimes IS 'Date and Timestamp when the record is soft deleted with is_deleted=TRUE';


--
-- Name: licensekey_list; Type: TABLE; Schema: keymgr; Owner: -
--

CREATE TABLE keymgr.licensekey_list (
    license_key character varying(255) NOT NULL,
    created_dtime timestamp without time zone,
    expiry_dtime timestamp without time zone,
    is_active boolean NOT NULL,
    cr_by character varying(256) NOT NULL,
    cr_dtimes timestamp without time zone NOT NULL,
    upd_by character varying(256),
    upd_dtimes timestamp without time zone,
    is_deleted boolean DEFAULT false,
    del_dtimes timestamp without time zone
);


--
-- Name: TABLE licensekey_list; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON TABLE keymgr.licensekey_list IS 'License Key : Holds list of license keys which will be used by TSPs';


--
-- Name: COLUMN licensekey_list.license_key; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_list.license_key IS 'License Key : License key which is created to map partners, license key will have information related to authentication type access.';


--
-- Name: COLUMN licensekey_list.created_dtime; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_list.created_dtime IS 'Created Date and Time : Licence key created date and time';


--
-- Name: COLUMN licensekey_list.expiry_dtime; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_list.expiry_dtime IS 'Expiry Date and Time: Expiry date and time of license key';


--
-- Name: COLUMN licensekey_list.is_active; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_list.is_active IS 'Flag to mark whether the record is Active or In-active';


--
-- Name: COLUMN licensekey_list.cr_by; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_list.cr_by IS 'Created By : ID or name of the user who create / insert record';


--
-- Name: COLUMN licensekey_list.cr_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_list.cr_dtimes IS 'Created DateTimestamp : Date and Timestamp when the record is created/inserted';


--
-- Name: COLUMN licensekey_list.upd_by; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_list.upd_by IS 'Updated By : ID or name of the user who update the record with new values';


--
-- Name: COLUMN licensekey_list.upd_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_list.upd_dtimes IS 'Updated DateTimestamp : Date and Timestamp when any of the fields in the record is updated with new values.';


--
-- Name: COLUMN licensekey_list.is_deleted; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_list.is_deleted IS 'IS_Deleted : Flag to mark whether the record is Soft deleted.';


--
-- Name: COLUMN licensekey_list.del_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_list.del_dtimes IS 'Deleted DateTimestamp : Date and Timestamp when the record is soft deleted with is_deleted=TRUE''';


--
-- Name: licensekey_permission; Type: TABLE; Schema: keymgr; Owner: -
--

CREATE TABLE keymgr.licensekey_permission (
    license_key character varying(255) NOT NULL,
    permission character varying(512),
    is_active boolean NOT NULL,
    cr_by character varying(256) NOT NULL,
    cr_dtimes timestamp without time zone NOT NULL,
    upd_by character varying(256),
    upd_dtimes timestamp without time zone,
    is_deleted boolean DEFAULT false,
    del_dtimes timestamp without time zone
);


--
-- Name: TABLE licensekey_permission; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON TABLE keymgr.licensekey_permission IS 'Permissions: List of permissions associated with license key';


--
-- Name: COLUMN licensekey_permission.license_key; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_permission.license_key IS 'License Key : License key which is mapped to TSP, This will refer to master.licensekey_list.license_key';


--
-- Name: COLUMN licensekey_permission.permission; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_permission.permission IS 'Permission: List of authentication permission which are assigned to license key';


--
-- Name: COLUMN licensekey_permission.is_active; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_permission.is_active IS 'Flag to mark whether the record is Active or In-active';


--
-- Name: COLUMN licensekey_permission.cr_by; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_permission.cr_by IS 'Created By : ID or name of the user who create / insert record';


--
-- Name: COLUMN licensekey_permission.cr_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_permission.cr_dtimes IS 'Created DateTimestamp : Date and Timestamp when the record is created/inserted';


--
-- Name: COLUMN licensekey_permission.upd_by; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_permission.upd_by IS 'Updated By : ID or name of the user who update the record with new values';


--
-- Name: COLUMN licensekey_permission.upd_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_permission.upd_dtimes IS 'Updated DateTimestamp : Date and Timestamp when any of the fields in the record is updated with new values.';


--
-- Name: COLUMN licensekey_permission.is_deleted; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_permission.is_deleted IS 'IS_Deleted : Flag to mark whether the record is Soft deleted.';


--
-- Name: COLUMN licensekey_permission.del_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.licensekey_permission.del_dtimes IS 'Deleted DateTimestamp : Date and Timestamp when the record is soft deleted with is_deleted=TRUE''';


--
-- Name: partner_cert_store; Type: TABLE; Schema: keymgr; Owner: -
--

CREATE TABLE keymgr.partner_cert_store (
    cert_id character varying(36) NOT NULL,
    cert_subject character varying(500) NOT NULL,
    cert_issuer character varying(500) NOT NULL,
    issuer_id character varying(36) NOT NULL,
    cert_not_before timestamp without time zone,
    cert_not_after timestamp without time zone,
    partner_domain character varying(36),
    cert_data character varying,
    signed_cert_data character varying,
    key_usage character varying(150),
    organization_name character varying(120),
    cert_thumbprint character varying(100),
    cert_serial_no character varying(50),
    cr_by character varying(256),
    cr_dtimes timestamp without time zone,
    upd_by character varying(256),
    upd_dtimes timestamp without time zone,
    is_deleted boolean DEFAULT false,
    del_dtimes timestamp without time zone
);


--
-- Name: TABLE partner_cert_store; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON TABLE keymgr.partner_cert_store IS 'Partner Certificate Store: Store details of all the certificate provided by partners which will be used by MOSIP';


--
-- Name: COLUMN partner_cert_store.cert_id; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.cert_id IS 'Unique ID (UUID) will be generated and assigned to the uploaded Partner/DP/FTM certificate.';


--
-- Name: COLUMN partner_cert_store.cert_subject; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.cert_subject IS 'Certificate Subject: Subject DN of the certificate.';


--
-- Name: COLUMN partner_cert_store.cert_issuer; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.cert_issuer IS 'Certificate Issuer:Issuer DN of the certificate';


--
-- Name: COLUMN partner_cert_store.issuer_id; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.issuer_id IS 'Issuer UUID of the certificate. (Issuer certificate should be available in the DB)';


--
-- Name: COLUMN partner_cert_store.cert_not_before; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.cert_not_before IS 'Certificate Start Date: Certificate Interval - Validity Start Date & Time';


--
-- Name: COLUMN partner_cert_store.cert_not_after; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.cert_not_after IS 'Certificate Validity end Date: Certificate Interval - Validity End Date & Time';


--
-- Name: COLUMN partner_cert_store.partner_domain; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.partner_domain IS 'Partner Domain: Domain of Partner example..Type are Auth Provider, DP, FTM';


--
-- Name: COLUMN partner_cert_store.cert_data; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.cert_data IS 'Certificate Data: PEM Encoded actual certificate data.';


--
-- Name: COLUMN partner_cert_store.signed_cert_data; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.signed_cert_data IS 'Signed Certificate Data: PEM Encoded signed certificate data.';


--
-- Name: COLUMN partner_cert_store.key_usage; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.key_usage IS 'Key Usage: Key Usage for the certificate issued.';


--
-- Name: COLUMN partner_cert_store.organization_name; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.organization_name IS 'Organization Name: Organization Name of the partner';


--
-- Name: COLUMN partner_cert_store.cert_thumbprint; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.cert_thumbprint IS 'Certificate Thumb Print: SHA1 generated certificate thumbprint.';


--
-- Name: COLUMN partner_cert_store.cert_serial_no; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.cert_serial_no IS 'Certificate Serial No: Serial Number of the certificate.';


--
-- Name: COLUMN partner_cert_store.cr_by; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.cr_by IS 'Created By : ID or name of the user who create / insert record';


--
-- Name: COLUMN partner_cert_store.cr_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.cr_dtimes IS 'Created DateTimestamp : Date and Timestamp when the record is created/inserted';


--
-- Name: COLUMN partner_cert_store.upd_by; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.upd_by IS 'Updated By : ID or name of the user who update the record with new values';


--
-- Name: COLUMN partner_cert_store.upd_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.upd_dtimes IS 'Updated DateTimestamp : Date and Timestamp when any of the fields in the record is updated with new values.';


--
-- Name: COLUMN partner_cert_store.is_deleted; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.is_deleted IS 'IS_Deleted : Flag to mark whether the record is Soft deleted.';


--
-- Name: COLUMN partner_cert_store.del_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.partner_cert_store.del_dtimes IS 'Deleted DateTimestamp : Date and Timestamp when the record is soft deleted with is_deleted=TRUE';


--
-- Name: tsp_licensekey_map; Type: TABLE; Schema: keymgr; Owner: -
--

CREATE TABLE keymgr.tsp_licensekey_map (
    tsp_id character varying(36) NOT NULL,
    license_key character varying(255) NOT NULL,
    is_active boolean NOT NULL,
    cr_by character varying(256) NOT NULL,
    cr_dtimes timestamp without time zone NOT NULL,
    upd_by character varying(256),
    upd_dtimes timestamp without time zone,
    is_deleted boolean DEFAULT false,
    del_dtimes timestamp without time zone
);


--
-- Name: TABLE tsp_licensekey_map; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON TABLE keymgr.tsp_licensekey_map IS 'TSP License keys : TSP and License key mapping';


--
-- Name: COLUMN tsp_licensekey_map.tsp_id; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.tsp_licensekey_map.tsp_id IS 'TSP ID: ID of the thirdparty service provider';


--
-- Name: COLUMN tsp_licensekey_map.license_key; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.tsp_licensekey_map.license_key IS 'License Key : License key which is mapped to TSP, This will refer to master.licensekey_list.license_key';


--
-- Name: COLUMN tsp_licensekey_map.is_active; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.tsp_licensekey_map.is_active IS 'Flag to mark whether the record is Active or In-active';


--
-- Name: COLUMN tsp_licensekey_map.cr_by; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.tsp_licensekey_map.cr_by IS 'Created By : ID or name of the user who create / insert record';


--
-- Name: COLUMN tsp_licensekey_map.cr_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.tsp_licensekey_map.cr_dtimes IS 'Created DateTimestamp : Date and Timestamp when the record is created/inserted';


--
-- Name: COLUMN tsp_licensekey_map.upd_by; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.tsp_licensekey_map.upd_by IS 'Updated By : ID or name of the user who update the record with new values';


--
-- Name: COLUMN tsp_licensekey_map.upd_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.tsp_licensekey_map.upd_dtimes IS 'Updated DateTimestamp : Date and Timestamp when any of the fields in the record is updated with new values.';


--
-- Name: COLUMN tsp_licensekey_map.is_deleted; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.tsp_licensekey_map.is_deleted IS 'IS_Deleted : Flag to mark whether the record is Soft deleted.';


--
-- Name: COLUMN tsp_licensekey_map.del_dtimes; Type: COMMENT; Schema: keymgr; Owner: -
--

COMMENT ON COLUMN keymgr.tsp_licensekey_map.del_dtimes IS 'Deleted DateTimestamp : Date and Timestamp when the record is soft deleted with is_deleted=TRUE''';


--
-- Name: ca_cert_store cert_thumbprint_unique; Type: CONSTRAINT; Schema: keymgr; Owner: -
--

ALTER TABLE ONLY keymgr.ca_cert_store
    ADD CONSTRAINT cert_thumbprint_unique UNIQUE (cert_thumbprint, partner_domain);


--
-- Name: ca_cert_store pk_cacs_id; Type: CONSTRAINT; Schema: keymgr; Owner: -
--

ALTER TABLE ONLY keymgr.ca_cert_store
    ADD CONSTRAINT pk_cacs_id PRIMARY KEY (cert_id);


--
-- Name: data_encrypt_keystore pk_dekstr_id; Type: CONSTRAINT; Schema: keymgr; Owner: -
--

ALTER TABLE ONLY keymgr.data_encrypt_keystore
    ADD CONSTRAINT pk_dekstr_id PRIMARY KEY (id);


--
-- Name: key_alias pk_keymals_id; Type: CONSTRAINT; Schema: keymgr; Owner: -
--

ALTER TABLE ONLY keymgr.key_alias
    ADD CONSTRAINT pk_keymals_id PRIMARY KEY (id);


--
-- Name: key_policy_def pk_keypdef_id; Type: CONSTRAINT; Schema: keymgr; Owner: -
--

ALTER TABLE ONLY keymgr.key_policy_def
    ADD CONSTRAINT pk_keypdef_id PRIMARY KEY (app_id);


--
-- Name: key_store pk_keystr_id; Type: CONSTRAINT; Schema: keymgr; Owner: -
--

ALTER TABLE ONLY keymgr.key_store
    ADD CONSTRAINT pk_keystr_id PRIMARY KEY (id);


--
-- Name: licensekey_list pk_lkeylst; Type: CONSTRAINT; Schema: keymgr; Owner: -
--

ALTER TABLE ONLY keymgr.licensekey_list
    ADD CONSTRAINT pk_lkeylst PRIMARY KEY (license_key);


--
-- Name: licensekey_permission pk_lkeyper; Type: CONSTRAINT; Schema: keymgr; Owner: -
--

ALTER TABLE ONLY keymgr.licensekey_permission
    ADD CONSTRAINT pk_lkeyper PRIMARY KEY (license_key);


--
-- Name: partner_cert_store pk_parcs_id; Type: CONSTRAINT; Schema: keymgr; Owner: -
--

ALTER TABLE ONLY keymgr.partner_cert_store
    ADD CONSTRAINT pk_parcs_id PRIMARY KEY (cert_id);


--
-- Name: tsp_licensekey_map pk_tsplkeym; Type: CONSTRAINT; Schema: keymgr; Owner: -
--

ALTER TABLE ONLY keymgr.tsp_licensekey_map
    ADD CONSTRAINT pk_tsplkeym PRIMARY KEY (tsp_id, license_key);


--
-- Name: key_alias uni_ident_const; Type: CONSTRAINT; Schema: keymgr; Owner: -
--

ALTER TABLE ONLY keymgr.key_alias
    ADD CONSTRAINT uni_ident_const UNIQUE (uni_ident);


--
-- Name: licensekey_permission fk_lkeyper; Type: FK CONSTRAINT; Schema: keymgr; Owner: -
--

ALTER TABLE ONLY keymgr.licensekey_permission
    ADD CONSTRAINT fk_lkeyper FOREIGN KEY (license_key) REFERENCES keymgr.licensekey_list(license_key);


--
-- Name: tsp_licensekey_map fk_tsplkeym; Type: FK CONSTRAINT; Schema: keymgr; Owner: -
--

ALTER TABLE ONLY keymgr.tsp_licensekey_map
    ADD CONSTRAINT fk_tsplkeym FOREIGN KEY (license_key) REFERENCES keymgr.licensekey_list(license_key);


--
-- PostgreSQL database dump complete
--

