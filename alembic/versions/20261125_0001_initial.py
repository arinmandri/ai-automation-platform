"""Initial secure multi-tenant schema.

Revision ID: 20261125_0001
Revises:
Create Date: 2026-11-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261125_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA_SQL = r"""
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA app AUTHORIZATION app_owner;
CREATE SCHEMA control AUTHORIZATION app_owner;
REVOKE ALL ON SCHEMA app FROM PUBLIC;
REVOKE ALL ON SCHEMA control FROM PUBLIC;

CREATE FUNCTION app.current_workspace_id()
RETURNS uuid
LANGUAGE sql
STABLE
SET search_path = pg_catalog
AS $$
    SELECT NULLIF(current_setting('app.workspace_id', true), '')::uuid
$$;

CREATE FUNCTION app.current_actor_id()
RETURNS uuid
LANGUAGE sql
STABLE
SET search_path = pg_catalog
AS $$
    SELECT NULLIF(current_setting('app.actor_id', true), '')::uuid
$$;

CREATE TABLE app.users (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cognito_sub         text NOT NULL UNIQUE,
    normalized_email    text NOT NULL,
    display_name        text,
    status              text NOT NULL DEFAULT 'ACTIVE'
                        CHECK (status IN ('ACTIVE', 'DISABLED', 'DELETED')),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.user_identities (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             uuid NOT NULL REFERENCES app.users(id),
    issuer              text NOT NULL,
    subject             text NOT NULL,
    provider            text NOT NULL,
    email_at_link       text,
    linked_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (issuer, subject)
);

CREATE TABLE app.workspaces (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name                text NOT NULL,
    slug                text NOT NULL UNIQUE,
    timezone            text NOT NULL DEFAULT 'UTC',
    status              text NOT NULL DEFAULT 'ACTIVE'
                        CHECK (status IN (
                            'ACTIVE', 'SUSPENDED',
                            'PENDING_DELETION', 'DELETED'
                        )),
    deletion_due_at     timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.memberships (
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    user_id             uuid NOT NULL REFERENCES app.users(id),
    role                text NOT NULL
                        CHECK (role IN ('OWNER', 'ADMIN', 'MEMBER')),
    status              text NOT NULL DEFAULT 'ACTIVE'
                        CHECK (status IN ('INVITED', 'ACTIVE', 'SUSPENDED')),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE app.invitations (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    normalized_email    text NOT NULL,
    role                text NOT NULL
                        CHECK (role IN ('ADMIN', 'MEMBER')),
    token_hash          text NOT NULL UNIQUE,
    status              text NOT NULL DEFAULT 'PENDING'
                        CHECK (status IN (
                            'PENDING', 'ACCEPTED', 'REVOKED', 'EXPIRED'
                        )),
    invited_by          uuid NOT NULL REFERENCES app.users(id),
    accepted_by         uuid REFERENCES app.users(id),
    expires_at          timestamptz NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    accepted_at         timestamptz,
    UNIQUE (workspace_id, id)
);

CREATE INDEX invitations_pending_email_idx
    ON app.invitations(workspace_id, normalized_email)
    WHERE status = 'PENDING';

CREATE TABLE app.documents (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    filename            text NOT NULL,
    content_type        text NOT NULL,
    size_bytes          bigint NOT NULL CHECK (size_bytes >= 0),
    sha256              text NOT NULL,
    s3_bucket           text NOT NULL,
    s3_key              text NOT NULL,
    status              text NOT NULL DEFAULT 'PENDING'
                        CHECK (status IN (
                            'PENDING', 'READY', 'FAILED', 'DELETED'
                        )),
    uploaded_by         uuid NOT NULL REFERENCES app.users(id),
    retention_until     timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    deleted_at          timestamptz,
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, s3_key)
);

CREATE TABLE app.agents (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    name                text NOT NULL,
    description         text,
    status              text NOT NULL DEFAULT 'DRAFT'
                        CHECK (status IN ('DRAFT', 'ACTIVE', 'ARCHIVED')),
    current_version_id  uuid,
    created_by          uuid NOT NULL REFERENCES app.users(id),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, id)
);

CREATE TABLE app.agent_versions (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    agent_id            uuid NOT NULL,
    version             integer NOT NULL CHECK (version > 0),
    instructions        text NOT NULL,
    model_config        jsonb NOT NULL,
    tool_config         jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_by          uuid NOT NULL REFERENCES app.users(id),
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, agent_id, version),
    FOREIGN KEY (workspace_id, agent_id)
        REFERENCES app.agents(workspace_id, id)
);

ALTER TABLE app.agents
    ADD CONSTRAINT agents_current_version_fk
    FOREIGN KEY (workspace_id, current_version_id)
    REFERENCES app.agent_versions(workspace_id, id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE app.connections (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    provider            text NOT NULL
                        CHECK (provider IN ('SLACK', 'REST', 'WEBHOOK')),
    display_name        text NOT NULL,
    base_url            text,
    allowed_hosts       text[] NOT NULL DEFAULT '{}',
    encrypted_payload   bytea NOT NULL,
    encrypted_data_key  bytea NOT NULL,
    nonce               bytea NOT NULL,
    kms_key_version     text NOT NULL,
    status              text NOT NULL DEFAULT 'ACTIVE'
                        CHECK (status IN ('ACTIVE', 'INVALID', 'REVOKED')),
    created_by          uuid NOT NULL REFERENCES app.users(id),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, id)
);

CREATE TABLE app.connection_operations (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    connection_id       uuid NOT NULL,
    operation_key       text NOT NULL,
    http_method         text NOT NULL
                        CHECK (http_method IN ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')),
    path_template       text NOT NULL,
    input_schema        jsonb NOT NULL,
    output_schema       jsonb,
    risk_level          text NOT NULL
                        CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    timeout_seconds     integer NOT NULL DEFAULT 30
                        CHECK (timeout_seconds BETWEEN 1 AND 120),
    max_response_bytes  integer NOT NULL DEFAULT 1048576
                        CHECK (max_response_bytes BETWEEN 1 AND 10485760),
    enabled             boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, connection_id, operation_key),
    FOREIGN KEY (workspace_id, connection_id)
        REFERENCES app.connections(workspace_id, id)
);

CREATE TABLE app.schedules (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    agent_id            uuid NOT NULL,
    cron_expression     text NOT NULL,
    timezone            text NOT NULL,
    misfire_policy      text NOT NULL DEFAULT 'FIRE_ONCE'
                        CHECK (misfire_policy IN ('SKIP', 'FIRE_ONCE', 'CATCH_UP')),
    misfire_grace_sec   integer NOT NULL DEFAULT 900 CHECK (misfire_grace_sec >= 0),
    max_catch_up        integer NOT NULL DEFAULT 3 CHECK (max_catch_up BETWEEN 1 AND 10),
    input_template      jsonb NOT NULL DEFAULT '{}'::jsonb,
    enabled             boolean NOT NULL DEFAULT true,
    last_scheduled_for  timestamptz,
    next_run_at         timestamptz NOT NULL,
    lease_owner         uuid,
    lease_expires_at    timestamptz,
    fencing_token       bigint NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, agent_id)
        REFERENCES app.agents(workspace_id, id),
    CHECK ((lease_owner IS NULL) = (lease_expires_at IS NULL))
);

CREATE INDEX schedules_due_idx
    ON app.schedules(next_run_at)
    WHERE enabled = true;

CREATE TABLE app.executions (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    agent_version_id    uuid NOT NULL,
    schedule_id         uuid,
    scheduled_for       timestamptz,
    trigger_type        text NOT NULL
                        CHECK (trigger_type IN ('MANUAL', 'SCHEDULE', 'RETRY', 'WEBHOOK')),
    status              text NOT NULL DEFAULT 'QUEUED'
                        CHECK (status IN (
                            'PENDING', 'QUEUED', 'RUNNING', 'WAITING_APPROVAL',
                            'RETRY_WAIT', 'CANCEL_REQUESTED', 'RECONCILING',
                            'UNKNOWN', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'REJECTED'
                        )),
    input               jsonb NOT NULL,
    result              jsonb,
    checkpoint          jsonb,
    failure_code        text,
    failure_detail      jsonb,
    active_attempt_id   uuid,
    lease_owner         uuid,
    lease_expires_at    timestamptz,
    fencing_token       bigint NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
    next_dispatch_at    timestamptz,
    dispatch_count      integer NOT NULL DEFAULT 0 CHECK (dispatch_count >= 0),
    cancel_requested_at timestamptz,
    created_by          uuid REFERENCES app.users(id),
    created_at          timestamptz NOT NULL DEFAULT now(),
    started_at          timestamptz,
    finished_at         timestamptz,
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, schedule_id, scheduled_for),
    FOREIGN KEY (workspace_id, agent_version_id)
        REFERENCES app.agent_versions(workspace_id, id),
    FOREIGN KEY (workspace_id, schedule_id)
        REFERENCES app.schedules(workspace_id, id),
    CHECK ((lease_owner IS NULL) = (lease_expires_at IS NULL))
);

CREATE INDEX executions_status_idx
    ON app.executions(workspace_id, status, created_at);
CREATE INDEX executions_recovery_idx
    ON app.executions(status, next_dispatch_at)
    WHERE status IN ('QUEUED', 'RETRY_WAIT');
CREATE INDEX executions_expired_lease_idx
    ON app.executions(lease_expires_at)
    WHERE status IN ('RUNNING', 'CANCEL_REQUESTED');

CREATE TABLE app.execution_attempts (
    id                  uuid PRIMARY KEY,
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    execution_id        uuid NOT NULL,
    attempt_no          integer NOT NULL CHECK (attempt_no > 0),
    fencing_token       bigint NOT NULL,
    worker_id           uuid NOT NULL,
    status              text NOT NULL
                        CHECK (status IN (
                            'RUNNING', 'SUCCEEDED', 'FAILED',
                            'LEASE_LOST', 'CANCELLED', 'RECONCILING'
                        )),
    started_at          timestamptz NOT NULL DEFAULT now(),
    heartbeat_at        timestamptz NOT NULL DEFAULT now(),
    ended_at            timestamptz,
    error_detail        jsonb,
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, execution_id, attempt_no),
    FOREIGN KEY (workspace_id, execution_id)
        REFERENCES app.executions(workspace_id, id)
);

ALTER TABLE app.executions
    ADD CONSTRAINT executions_active_attempt_fk
    FOREIGN KEY (workspace_id, active_attempt_id)
    REFERENCES app.execution_attempts(workspace_id, id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE app.execution_steps (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    execution_id        uuid NOT NULL,
    attempt_id          uuid NOT NULL,
    sequence_no         integer NOT NULL CHECK (sequence_no >= 0),
    step_type           text NOT NULL,
    status              text NOT NULL
                        CHECK (status IN (
                            'PLANNED', 'RUNNING', 'WAITING_APPROVAL',
                            'SUCCEEDED', 'FAILED', 'SKIPPED',
                            'RECONCILING', 'UNKNOWN'
                        )),
    input               jsonb NOT NULL,
    output              jsonb,
    idempotency_key     text NOT NULL,
    provider_request_id text,
    fencing_token       bigint NOT NULL,
    started_at          timestamptz,
    finished_at         timestamptz,
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, idempotency_key),
    FOREIGN KEY (workspace_id, execution_id)
        REFERENCES app.executions(workspace_id, id),
    FOREIGN KEY (workspace_id, attempt_id)
        REFERENCES app.execution_attempts(workspace_id, id)
);

CREATE TABLE app.approval_requests (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    execution_id        uuid NOT NULL,
    step_id             uuid NOT NULL,
    status              text NOT NULL DEFAULT 'PENDING'
                        CHECK (status IN (
                            'PENDING', 'APPROVED', 'REJECTED', 'EXPIRED', 'CONSUMED'
                        )),
    risk_level          text NOT NULL CHECK (risk_level IN ('HIGH', 'CRITICAL')),
    action_type         text NOT NULL,
    action_preview      jsonb NOT NULL,
    action_payload      jsonb NOT NULL,
    action_hash         text NOT NULL,
    requested_by        uuid REFERENCES app.users(id),
    decided_by          uuid REFERENCES app.users(id),
    decision_reason     text,
    expires_at          timestamptz NOT NULL,
    decided_at          timestamptz,
    consumed_at         timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, execution_id, step_id, action_hash),
    FOREIGN KEY (workspace_id, execution_id)
        REFERENCES app.executions(workspace_id, id),
    FOREIGN KEY (workspace_id, step_id)
        REFERENCES app.execution_steps(workspace_id, id)
);

CREATE TABLE app.external_call_attempts (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    execution_id        uuid NOT NULL,
    step_id             uuid NOT NULL,
    approval_id         uuid,
    connection_id       uuid NOT NULL,
    operation_id        uuid NOT NULL,
    idempotency_key     text NOT NULL,
    request_hash        text NOT NULL,
    status              text NOT NULL DEFAULT 'PREPARED'
                        CHECK (status IN (
                            'PREPARED', 'SENT', 'CONFIRMED',
                            'RECONCILING', 'UNKNOWN', 'FAILED'
                        )),
    fencing_token       bigint NOT NULL,
    provider_request_id text,
    response_metadata   jsonb,
    prepared_at         timestamptz NOT NULL DEFAULT now(),
    sent_at             timestamptz,
    confirmed_at        timestamptz,
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, idempotency_key),
    UNIQUE (workspace_id, approval_id),
    FOREIGN KEY (workspace_id, execution_id)
        REFERENCES app.executions(workspace_id, id),
    FOREIGN KEY (workspace_id, step_id)
        REFERENCES app.execution_steps(workspace_id, id),
    FOREIGN KEY (workspace_id, approval_id)
        REFERENCES app.approval_requests(workspace_id, id),
    FOREIGN KEY (workspace_id, connection_id)
        REFERENCES app.connections(workspace_id, id),
    FOREIGN KEY (workspace_id, operation_id)
        REFERENCES app.connection_operations(workspace_id, id)
);

CREATE TABLE app.outbox_events (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    event_type          text NOT NULL,
    aggregate_type      text NOT NULL,
    aggregate_id        uuid NOT NULL,
    deduplication_key   text NOT NULL UNIQUE,
    payload             jsonb NOT NULL,
    available_at        timestamptz NOT NULL DEFAULT now(),
    claimed_by          uuid,
    claim_expires_at    timestamptz,
    send_count          integer NOT NULL DEFAULT 0 CHECK (send_count >= 0),
    last_sent_at        timestamptz,
    last_error          text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, id),
    CHECK ((claimed_by IS NULL) = (claim_expires_at IS NULL))
);

CREATE INDEX outbox_available_idx
    ON app.outbox_events(available_at, claim_expires_at);

CREATE TABLE app.idempotency_keys (
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    scope               text NOT NULL,
    idempotency_key     text NOT NULL,
    request_hash        text NOT NULL,
    response_status     integer,
    response_body       jsonb,
    resource_id         uuid,
    created_at          timestamptz NOT NULL DEFAULT now(),
    expires_at          timestamptz NOT NULL,
    PRIMARY KEY (workspace_id, scope, idempotency_key)
);

CREATE TABLE app.workspace_budgets (
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    period_start        date NOT NULL,
    period_end          date NOT NULL,
    hard_limit_microusd bigint NOT NULL CHECK (hard_limit_microusd >= 0),
    spent_microusd      bigint NOT NULL DEFAULT 0 CHECK (spent_microusd >= 0),
    reserved_microusd   bigint NOT NULL DEFAULT 0 CHECK (reserved_microusd >= 0),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, period_start),
    CHECK (period_end > period_start)
);

CREATE TABLE app.budget_reservations (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    period_start        date NOT NULL,
    execution_id        uuid NOT NULL,
    step_id             uuid,
    deduplication_key   text NOT NULL,
    amount_microusd     bigint NOT NULL CHECK (amount_microusd >= 0),
    settled_microusd    bigint CHECK (settled_microusd >= 0),
    settlement_key      text,
    status              text NOT NULL DEFAULT 'ACTIVE'
                        CHECK (status IN ('ACTIVE', 'SETTLED', 'RELEASED', 'EXPIRED')),
    expires_at          timestamptz NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    settled_at          timestamptz,
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, deduplication_key),
    UNIQUE (workspace_id, settlement_key),
    FOREIGN KEY (workspace_id, period_start)
        REFERENCES app.workspace_budgets(workspace_id, period_start),
    FOREIGN KEY (workspace_id, execution_id)
        REFERENCES app.executions(workspace_id, id),
    FOREIGN KEY (workspace_id, step_id)
        REFERENCES app.execution_steps(workspace_id, id)
);

CREATE TABLE app.ai_usage_events (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    execution_id        uuid NOT NULL,
    step_id             uuid,
    reservation_id      uuid,
    provider            text NOT NULL,
    model               text NOT NULL,
    provider_request_id text,
    input_tokens        bigint NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    cached_input_tokens bigint NOT NULL DEFAULT 0 CHECK (cached_input_tokens >= 0),
    output_tokens       bigint NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    estimated           boolean NOT NULL DEFAULT false,
    cost_microusd       bigint NOT NULL CHECK (cost_microusd >= 0),
    price_snapshot      jsonb NOT NULL,
    occurred_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, execution_id)
        REFERENCES app.executions(workspace_id, id),
    FOREIGN KEY (workspace_id, step_id)
        REFERENCES app.execution_steps(workspace_id, id),
    FOREIGN KEY (workspace_id, reservation_id)
        REFERENCES app.budget_reservations(workspace_id, id)
);

CREATE UNIQUE INDEX ai_usage_reservation_once_idx
    ON app.ai_usage_events(workspace_id, reservation_id)
    WHERE reservation_id IS NOT NULL;

CREATE TABLE app.audit_logs (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        uuid NOT NULL REFERENCES app.workspaces(id),
    actor_type          text NOT NULL,
    actor_id            uuid,
    action              text NOT NULL,
    resource_type       text NOT NULL,
    resource_id         uuid,
    request_id          text,
    source_ip_hash      text,
    metadata            jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, id)
);

CREATE INDEX audit_logs_lookup_idx
    ON app.audit_logs(workspace_id, occurred_at DESC);

ALTER TABLE app.workspaces ENABLE ROW LEVEL SECURITY;
CREATE POLICY workspace_isolation ON app.workspaces
    USING (id = app.current_workspace_id())
    WITH CHECK (id = app.current_workspace_id());

DO $rls$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'memberships', 'invitations', 'documents', 'agents', 'agent_versions',
        'connections', 'connection_operations', 'schedules', 'executions',
        'execution_attempts', 'execution_steps', 'approval_requests',
        'external_call_attempts',
        'outbox_events', 'idempotency_keys', 'workspace_budgets',
        'budget_reservations', 'ai_usage_events', 'audit_logs'
    ]
    LOOP
        EXECUTE format('ALTER TABLE app.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON app.%I '
            'USING (workspace_id = app.current_workspace_id()) '
            'WITH CHECK (workspace_id = app.current_workspace_id())',
            table_name
        );
    END LOOP;
END
$rls$;
"""


FENCING_SQL = r"""
CREATE FUNCTION control.claim_execution(
    p_execution_id uuid,
    p_worker_id uuid,
    p_lease_seconds integer DEFAULT 60
)
RETURNS TABLE (
    workspace_id uuid,
    execution_id uuid,
    attempt_id uuid,
    fencing_token bigint,
    agent_version_id uuid,
    input jsonb,
    checkpoint jsonb
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, app, control
AS $$
DECLARE
    v_execution app.executions%ROWTYPE;
    v_attempt_id uuid := gen_random_uuid();
    v_attempt_no integer;
BEGIN
    IF p_lease_seconds NOT BETWEEN 15 AND 300 THEN
        RAISE EXCEPTION 'invalid lease duration';
    END IF;

    SELECT e.* INTO v_execution
      FROM app.executions AS e
     WHERE e.id = p_execution_id
     FOR UPDATE;

    IF NOT FOUND
       OR v_execution.status <> 'QUEUED'
       OR v_execution.cancel_requested_at IS NOT NULL THEN
        RETURN;
    END IF;

    SELECT COALESCE(MAX(a.attempt_no), 0) + 1
      INTO v_attempt_no
      FROM app.execution_attempts AS a
     WHERE a.workspace_id = v_execution.workspace_id
       AND a.execution_id = v_execution.id;

    UPDATE app.executions AS e
       SET status = 'RUNNING',
           active_attempt_id = v_attempt_id,
           lease_owner = p_worker_id,
           lease_expires_at = clock_timestamp() + make_interval(secs => p_lease_seconds),
           fencing_token = e.fencing_token + 1,
           started_at = COALESCE(e.started_at, clock_timestamp())
     WHERE e.id = v_execution.id
    RETURNING e.* INTO v_execution;

    INSERT INTO app.execution_attempts (
        id, workspace_id, execution_id, attempt_no,
        fencing_token, worker_id, status
    ) VALUES (
        v_attempt_id, v_execution.workspace_id, v_execution.id, v_attempt_no,
        v_execution.fencing_token, p_worker_id, 'RUNNING'
    );

    RETURN QUERY SELECT
        v_execution.workspace_id,
        v_execution.id,
        v_attempt_id,
        v_execution.fencing_token,
        v_execution.agent_version_id,
        v_execution.input,
        v_execution.checkpoint;
END
$$;

CREATE FUNCTION control.renew_execution_lease(
    p_execution_id uuid,
    p_worker_id uuid,
    p_fencing_token bigint,
    p_lease_seconds integer DEFAULT 60
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, app
AS $$
DECLARE
    v_updated integer;
BEGIN
    IF p_lease_seconds NOT BETWEEN 15 AND 300 THEN
        RAISE EXCEPTION 'invalid lease duration';
    END IF;

    UPDATE app.executions AS e
       SET lease_expires_at = clock_timestamp() + make_interval(secs => p_lease_seconds)
     WHERE e.id = p_execution_id
       AND e.lease_owner = p_worker_id
       AND e.fencing_token = p_fencing_token
       AND e.status IN ('RUNNING', 'CANCEL_REQUESTED')
       AND e.lease_expires_at > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;

CREATE FUNCTION control.apply_execution_progress(
    p_execution_id uuid,
    p_attempt_id uuid,
    p_worker_id uuid,
    p_fencing_token bigint,
    p_step_id uuid,
    p_sequence_no integer,
    p_step_type text,
    p_step_status text,
    p_step_input jsonb,
    p_step_output jsonb,
    p_idempotency_key text,
    p_checkpoint jsonb
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, app
AS $$
DECLARE
    v_execution app.executions%ROWTYPE;
    v_updated integer;
BEGIN
    SELECT e.* INTO v_execution
      FROM app.executions AS e
     WHERE e.id = p_execution_id
     FOR UPDATE;

    IF NOT FOUND
       OR v_execution.active_attempt_id <> p_attempt_id
       OR v_execution.lease_owner <> p_worker_id
       OR v_execution.fencing_token <> p_fencing_token
       OR v_execution.lease_expires_at <= clock_timestamp()
       OR v_execution.status NOT IN ('RUNNING', 'CANCEL_REQUESTED') THEN
        RAISE EXCEPTION 'execution lease lost' USING ERRCODE = 'P0001';
    END IF;

    UPDATE app.execution_attempts AS a
       SET heartbeat_at = clock_timestamp()
     WHERE a.workspace_id = v_execution.workspace_id
       AND a.id = p_attempt_id
       AND a.execution_id = p_execution_id
       AND a.worker_id = p_worker_id
       AND a.fencing_token = p_fencing_token
       AND a.status = 'RUNNING';

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 1 THEN
        RAISE EXCEPTION 'attempt fence mismatch' USING ERRCODE = 'P0001';
    END IF;

    INSERT INTO app.execution_steps (
        id, workspace_id, execution_id, attempt_id, sequence_no,
        step_type, status, input, output, idempotency_key,
        fencing_token, started_at, finished_at
    ) VALUES (
        p_step_id, v_execution.workspace_id, p_execution_id, p_attempt_id,
        p_sequence_no, p_step_type, p_step_status, p_step_input, p_step_output,
        p_idempotency_key, p_fencing_token, clock_timestamp(),
        CASE WHEN p_step_status IN ('SUCCEEDED', 'FAILED', 'SKIPPED', 'UNKNOWN')
             THEN clock_timestamp() ELSE NULL END
    )
    ON CONFLICT (workspace_id, idempotency_key) DO UPDATE
       SET status = EXCLUDED.status,
           output = EXCLUDED.output,
           finished_at = EXCLUDED.finished_at
     WHERE execution_steps.attempt_id = p_attempt_id
       AND execution_steps.fencing_token = p_fencing_token;

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 1 THEN
        RAISE EXCEPTION 'step fence mismatch' USING ERRCODE = 'P0001';
    END IF;

    UPDATE app.executions AS e
       SET checkpoint = p_checkpoint
     WHERE e.id = p_execution_id
       AND e.active_attempt_id = p_attempt_id
       AND e.lease_owner = p_worker_id
       AND e.fencing_token = p_fencing_token
       AND e.lease_expires_at > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 1 THEN
        RAISE EXCEPTION 'checkpoint fence mismatch' USING ERRCODE = 'P0001';
    END IF;
END
$$;

CREATE FUNCTION control.finish_execution(
    p_execution_id uuid,
    p_attempt_id uuid,
    p_worker_id uuid,
    p_fencing_token bigint,
    p_status text,
    p_result jsonb DEFAULT NULL,
    p_failure_code text DEFAULT NULL,
    p_failure_detail jsonb DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, app
AS $$
DECLARE
    v_workspace_id uuid;
    v_updated integer;
BEGIN
    IF p_status NOT IN ('SUCCEEDED', 'FAILED', 'CANCELLED', 'RECONCILING', 'UNKNOWN') THEN
        RAISE EXCEPTION 'invalid terminal or reconciliation status';
    END IF;

    UPDATE app.executions AS e
       SET status = p_status,
           result = p_result,
           failure_code = p_failure_code,
           failure_detail = p_failure_detail,
           lease_owner = NULL,
           lease_expires_at = NULL,
           active_attempt_id = NULL,
           finished_at = CASE WHEN p_status IN ('SUCCEEDED', 'FAILED', 'CANCELLED')
                              THEN clock_timestamp() ELSE NULL END
     WHERE e.id = p_execution_id
       AND e.active_attempt_id = p_attempt_id
       AND e.lease_owner = p_worker_id
       AND e.fencing_token = p_fencing_token
       AND e.lease_expires_at > clock_timestamp()
    RETURNING e.workspace_id INTO v_workspace_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'execution lease lost' USING ERRCODE = 'P0001';
    END IF;

    UPDATE app.execution_attempts AS a
       SET status = CASE WHEN p_status = 'CANCELLED' THEN 'CANCELLED'
                         WHEN p_status IN ('RECONCILING', 'UNKNOWN') THEN 'RECONCILING'
                         WHEN p_status = 'SUCCEEDED' THEN 'SUCCEEDED'
                         ELSE 'FAILED' END,
           ended_at = clock_timestamp(),
           error_detail = p_failure_detail
     WHERE a.workspace_id = v_workspace_id
       AND a.id = p_attempt_id
       AND a.worker_id = p_worker_id
       AND a.fencing_token = p_fencing_token
       AND a.status = 'RUNNING';

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 1 THEN
        RAISE EXCEPTION 'attempt fence mismatch' USING ERRCODE = 'P0001';
    END IF;
END
$$;
"""


PRIVILEGES_SQL = r"""
REVOKE ALL ON ALL TABLES IN SCHEMA app FROM PUBLIC, app_api, app_worker, app_control;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app FROM PUBLIC, app_api, app_worker, app_control;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA control FROM PUBLIC, app_api, app_worker, app_control;

GRANT USAGE ON SCHEMA app TO app_api, app_worker;
GRANT USAGE ON SCHEMA control TO app_worker, app_control;

GRANT EXECUTE ON FUNCTION app.current_workspace_id() TO app_api, app_worker;
GRANT EXECUTE ON FUNCTION app.current_actor_id() TO app_api, app_worker;

GRANT SELECT, UPDATE ON app.workspaces TO app_api;
GRANT SELECT ON app.memberships TO app_api;
GRANT SELECT, INSERT, UPDATE ON app.invitations TO app_api;
GRANT SELECT, INSERT, UPDATE ON app.documents TO app_api;
GRANT SELECT, INSERT, UPDATE ON app.agents TO app_api;
GRANT SELECT, INSERT ON app.agent_versions TO app_api;
GRANT SELECT, INSERT, UPDATE ON app.connections TO app_api;
GRANT SELECT, INSERT, UPDATE ON app.connection_operations TO app_api;
GRANT SELECT, INSERT, UPDATE ON app.schedules TO app_api;
GRANT SELECT ON
    app.executions, app.execution_attempts, app.execution_steps,
    app.external_call_attempts
TO app_api;
GRANT SELECT, UPDATE ON app.approval_requests TO app_api;
GRANT SELECT, INSERT ON app.idempotency_keys TO app_api;
GRANT SELECT ON app.workspace_budgets, app.budget_reservations, app.ai_usage_events TO app_api;
GRANT SELECT ON app.audit_logs TO app_api;

GRANT SELECT ON
    app.workspaces, app.agents, app.agent_versions, app.documents,
    app.connections, app.connection_operations, app.executions,
    app.execution_attempts, app.execution_steps, app.approval_requests,
    app.external_call_attempts,
    app.workspace_budgets, app.budget_reservations
TO app_worker;

GRANT EXECUTE ON FUNCTION control.claim_execution(uuid, uuid, integer) TO app_worker;
GRANT EXECUTE ON FUNCTION control.renew_execution_lease(uuid, uuid, bigint, integer)
    TO app_worker;
GRANT EXECUTE ON FUNCTION control.apply_execution_progress(
    uuid, uuid, uuid, bigint, uuid, integer, text, text,
    jsonb, jsonb, text, jsonb
) TO app_worker;
GRANT EXECUTE ON FUNCTION control.finish_execution(
    uuid, uuid, uuid, bigint, text, jsonb, text, jsonb
) TO app_worker;

ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA app
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA app
    REVOKE ALL ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA control
    REVOKE ALL ON FUNCTIONS FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)
    op.execute(FENCING_SQL)
    op.execute(PRIVILEGES_SQL)


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS control CASCADE")
    op.execute("DROP SCHEMA IF EXISTS app CASCADE")
