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


SET default_table_access_method = heap;

--
-- Name: approval_decision; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_decision (
    id character varying(36) NOT NULL,
    request_id character varying(36) NOT NULL,
    task_id character varying(36) NOT NULL,
    stage_order integer NOT NULL,
    actor character varying(128) NOT NULL,
    action character varying(16) NOT NULL,
    comment text,
    attachments_ref text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: approval_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_event (
    id character varying(36) NOT NULL,
    request_id character varying(36) NOT NULL,
    event_type character varying(32) NOT NULL,
    payload json NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: approval_policy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_policy (
    id character varying(36) NOT NULL,
    policy_key character varying(128) NOT NULL,
    version integer NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(1024),
    status character varying(16) NOT NULL,
    artifact_type character varying(128) NOT NULL,
    created_by character varying(128),
    forbid_self_approval boolean NOT NULL,
    forbid_repeat_approvers boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: approval_request; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_request (
    id character varying(36) NOT NULL,
    policy_id character varying(36) NOT NULL,
    policy_key character varying(128) NOT NULL,
    policy_version integer NOT NULL,
    artifact_type character varying(128) NOT NULL,
    artifact_id character varying(128) NOT NULL,
    source_service character varying(128) NOT NULL,
    requester character varying(128),
    context json NOT NULL,
    status character varying(16) NOT NULL,
    current_stage_order integer NOT NULL,
    callback_url text,
    callback_secret_id character varying(36),
    completed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: approval_stage; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_stage (
    id character varying(36) NOT NULL,
    policy_id character varying(36) NOT NULL,
    stage_order integer NOT NULL,
    name character varying(255) NOT NULL,
    mode character varying(32) NOT NULL,
    mode_value integer,
    sla_hours integer,
    parallel_group integer,
    skip_if json,
    on_empty character varying(8) NOT NULL,
    on_breach character varying(16),
    escalation_rules_json json,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: approval_task; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_task (
    id character varying(36) NOT NULL,
    request_id character varying(36) NOT NULL,
    stage_id character varying(36) NOT NULL,
    stage_order integer NOT NULL,
    assignee character varying(128) NOT NULL,
    assignee_name character varying(256),
    kind character varying(16) NOT NULL,
    delegated_from character varying(128),
    reassigned_from character varying(128),
    status character varying(16) NOT NULL,
    claimed_at timestamp with time zone,
    completed_at timestamp with time zone,
    due_at timestamp with time zone,
    decision_id character varying(36),
    search_text text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: approver_rule; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approver_rule (
    id character varying(36) NOT NULL,
    stage_id character varying(36) NOT NULL,
    rule_type character varying(16) NOT NULL,
    rule_value json NOT NULL,
    kind character varying(16) NOT NULL,
    required boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: audit_action; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_action (
    id character varying(36) NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    actor character varying(128) NOT NULL,
    actor_email character varying(255),
    action character varying(64) NOT NULL,
    resource_type character varying(32) NOT NULL,
    resource_id character varying(255) NOT NULL,
    before json,
    after json,
    metadata json,
    summary text
);


--
-- Name: callback_secret; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.callback_secret (
    id character varying(36) NOT NULL,
    caller_service character varying(128) NOT NULL,
    secret_hash character varying(128) NOT NULL,
    status character varying(16) NOT NULL,
    rotated_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: idempotency_key; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.idempotency_key (
    key character varying(255) NOT NULL,
    response_payload json NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: user_delegation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_delegation (
    id character varying(36) NOT NULL,
    user_id character varying(128) NOT NULL,
    delegate_to character varying(128) NOT NULL,
    starts_at timestamp with time zone NOT NULL,
    ends_at timestamp with time zone NOT NULL,
    reason text,
    created_by character varying(128),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: webhook_delivery; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.webhook_delivery (
    id character varying(36) NOT NULL,
    event_id character varying(36) NOT NULL,
    url text NOT NULL,
    attempt integer NOT NULL,
    status character varying(16) NOT NULL,
    next_attempt_at timestamp with time zone NOT NULL,
    last_attempt_at timestamp with time zone,
    last_status_code integer,
    last_error text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: approval_decision approval_decision_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_decision
    ADD CONSTRAINT approval_decision_pkey PRIMARY KEY (id);


--
-- Name: approval_event approval_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_event
    ADD CONSTRAINT approval_event_pkey PRIMARY KEY (id);


--
-- Name: approval_policy approval_policy_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_policy
    ADD CONSTRAINT approval_policy_pkey PRIMARY KEY (id);


--
-- Name: approval_request approval_request_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_request
    ADD CONSTRAINT approval_request_pkey PRIMARY KEY (id);


--
-- Name: approval_stage approval_stage_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_stage
    ADD CONSTRAINT approval_stage_pkey PRIMARY KEY (id);


--
-- Name: approval_task approval_task_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_task
    ADD CONSTRAINT approval_task_pkey PRIMARY KEY (id);


--
-- Name: approver_rule approver_rule_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approver_rule
    ADD CONSTRAINT approver_rule_pkey PRIMARY KEY (id);


--
-- Name: audit_action audit_action_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_action
    ADD CONSTRAINT audit_action_pkey PRIMARY KEY (id);


--
-- Name: callback_secret callback_secret_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.callback_secret
    ADD CONSTRAINT callback_secret_pkey PRIMARY KEY (id);


--
-- Name: idempotency_key idempotency_key_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.idempotency_key
    ADD CONSTRAINT idempotency_key_pkey PRIMARY KEY (key);


--
-- Name: approval_policy uq_policy_key_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_policy
    ADD CONSTRAINT uq_policy_key_version UNIQUE (policy_key, version);


--
-- Name: approval_stage uq_stage_policy_order; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_stage
    ADD CONSTRAINT uq_stage_policy_order UNIQUE (policy_id, stage_order);


--
-- Name: user_delegation user_delegation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_delegation
    ADD CONSTRAINT user_delegation_pkey PRIMARY KEY (id);


--
-- Name: webhook_delivery webhook_delivery_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_delivery
    ADD CONSTRAINT webhook_delivery_pkey PRIMARY KEY (id);


--
-- Name: idx_audit_actor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_actor ON public.audit_action USING btree (actor);


--
-- Name: idx_audit_occurred_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_occurred_at ON public.audit_action USING btree (occurred_at);


--
-- Name: idx_audit_resource; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_resource ON public.audit_action USING btree (resource_type, resource_id);


--
-- Name: idx_decision_request; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_decision_request ON public.approval_decision USING btree (request_id);


--
-- Name: idx_delegation_user_window; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_delegation_user_window ON public.user_delegation USING btree (user_id, starts_at, ends_at);


--
-- Name: idx_delivery_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_delivery_event ON public.webhook_delivery USING btree (event_id);


--
-- Name: idx_delivery_status_next; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_delivery_status_next ON public.webhook_delivery USING btree (status, next_attempt_at);


--
-- Name: idx_event_request_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_event_request_created ON public.approval_event USING btree (request_id, created_at);


--
-- Name: idx_idempotency_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_idempotency_created ON public.idempotency_key USING btree (created_at);


--
-- Name: idx_policy_key_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_policy_key_status ON public.approval_policy USING btree (policy_key, status);


--
-- Name: idx_request_artifact; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_request_artifact ON public.approval_request USING btree (artifact_type, artifact_id);


--
-- Name: idx_request_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_request_status ON public.approval_request USING btree (status);


--
-- Name: idx_task_assignee_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_assignee_status ON public.approval_task USING btree (assignee, status);


--
-- Name: idx_task_request_stage; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_request_stage ON public.approval_task USING btree (request_id, stage_order);


--
-- Name: idx_task_search_text_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_search_text_gin ON public.approval_task USING gin (search_text public.gin_trgm_ops);


--
-- Name: ix_approval_decision_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_approval_decision_task_id ON public.approval_decision USING btree (task_id);


--
-- Name: approval_decision approval_decision_request_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_decision
    ADD CONSTRAINT approval_decision_request_id_fkey FOREIGN KEY (request_id) REFERENCES public.approval_request(id) ON DELETE CASCADE;


--
-- Name: approval_decision approval_decision_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_decision
    ADD CONSTRAINT approval_decision_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.approval_task(id);


--
-- Name: approval_event approval_event_request_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_event
    ADD CONSTRAINT approval_event_request_id_fkey FOREIGN KEY (request_id) REFERENCES public.approval_request(id) ON DELETE CASCADE;


--
-- Name: approval_request approval_request_callback_secret_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_request
    ADD CONSTRAINT approval_request_callback_secret_id_fkey FOREIGN KEY (callback_secret_id) REFERENCES public.callback_secret(id);


--
-- Name: approval_request approval_request_policy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_request
    ADD CONSTRAINT approval_request_policy_id_fkey FOREIGN KEY (policy_id) REFERENCES public.approval_policy(id);


--
-- Name: approval_stage approval_stage_policy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_stage
    ADD CONSTRAINT approval_stage_policy_id_fkey FOREIGN KEY (policy_id) REFERENCES public.approval_policy(id) ON DELETE CASCADE;


--
-- Name: approval_task approval_task_decision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_task
    ADD CONSTRAINT approval_task_decision_id_fkey FOREIGN KEY (decision_id) REFERENCES public.approval_decision(id);


--
-- Name: approval_task approval_task_request_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_task
    ADD CONSTRAINT approval_task_request_id_fkey FOREIGN KEY (request_id) REFERENCES public.approval_request(id) ON DELETE CASCADE;


--
-- Name: approval_task approval_task_stage_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_task
    ADD CONSTRAINT approval_task_stage_id_fkey FOREIGN KEY (stage_id) REFERENCES public.approval_stage(id);


--
-- Name: approver_rule approver_rule_stage_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approver_rule
    ADD CONSTRAINT approver_rule_stage_id_fkey FOREIGN KEY (stage_id) REFERENCES public.approval_stage(id) ON DELETE CASCADE;


--
-- Name: webhook_delivery webhook_delivery_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_delivery
    ADD CONSTRAINT webhook_delivery_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.approval_event(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

