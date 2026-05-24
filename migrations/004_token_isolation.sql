-- ============================================================
-- Migration 004 — Token Isolation + Execution Context
-- ============================================================
-- Adds:
--   - Audit columns to microsoft_platform_tokens
--   - task_execution_log  (every operation has an owner)
--   - owner_user_id to mail_report_schedules + mail_alert_rules
--   - user_notifications  (token expiry alerts)
--   - Indexes + audit view
-- ============================================================

BEGIN;

-- ── Audit columns for microsoft_platform_tokens ───────────────────────────────
ALTER TABLE microsoft_platform_tokens
  ADD COLUMN IF NOT EXISTS last_used_at         TIMESTAMP,
  ADD COLUMN IF NOT EXISTS use_count            INTEGER   NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_refresh_error   TEXT,
  ADD COLUMN IF NOT EXISTS refresh_error_count  INTEGER   NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS is_valid             BOOLEAN   NOT NULL DEFAULT TRUE;
-- is_valid = FALSE when refresh fails definitively (≥3 consecutive errors).
-- User must reconnect from /settings/microsoft.

-- ── task_execution_log ────────────────────────────────────────────────────────
-- Every operation — scheduled, manual, webhook, system — creates a row here.
-- No operation without an explicit owner_user_id.
CREATE TABLE IF NOT EXISTS task_execution_log (
  id                   UUID      PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id            UUID      NOT NULL,

  -- The "owner" of this execution.
  -- For cron jobs: the user who configured the task.
  -- For manual requests: the user who triggered it.
  owner_user_id        UUID      REFERENCES users(id),

  -- How it was triggered
  triggered_by         VARCHAR   NOT NULL
                         CHECK (triggered_by IN ('scheduled','manual','webhook','system')),

  -- Who pressed the button (may differ from owner for delegated ops)
  triggered_by_user_id UUID      REFERENCES users(id),

  -- What task
  task_type            VARCHAR   NOT NULL,
  -- 'send_report' | 'check_anomaly' | 'process_email'
  -- 'read_onedrive' | 'read_calendar' | 'read_mail'
  task_detail          JSONB,

  -- Microsoft token usage
  used_microsoft_token    BOOLEAN NOT NULL DEFAULT FALSE,
  token_owner_user_id     UUID    REFERENCES users(id),
  -- INVARIANT: token_owner_user_id = owner_user_id always.
  -- If they differ: CRITICAL security bug — page on-call immediately.

  -- Result
  status       VARCHAR  NOT NULL DEFAULT 'running'
                 CHECK (status IN ('running','completed','failed',
                                   'token_expired','no_permission')),
  error_detail   TEXT,
  result_summary TEXT,

  started_at   TIMESTAMP NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_task_log_owner
  ON task_execution_log (owner_user_id);
CREATE INDEX IF NOT EXISTS idx_task_log_tenant
  ON task_execution_log (tenant_id);
CREATE INDEX IF NOT EXISTS idx_task_log_status
  ON task_execution_log (status);
CREATE INDEX IF NOT EXISTS idx_task_log_started
  ON task_execution_log (started_at DESC);

-- ── mail_report_schedules — add owner_user_id ─────────────────────────────────
ALTER TABLE mail_report_schedules
  ADD COLUMN IF NOT EXISTS owner_user_id              UUID      REFERENCES users(id),
  ADD COLUMN IF NOT EXISTS requires_microsoft_token   BOOLEAN   NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS last_execution_id          UUID      REFERENCES task_execution_log(id),
  ADD COLUMN IF NOT EXISTS last_token_error_at        TIMESTAMP,
  ADD COLUMN IF NOT EXISTS notify_on_token_error      BOOLEAN   NOT NULL DEFAULT TRUE;
-- owner_user_id: the user whose Microsoft token is used when this schedule fires.
-- Schedules with owner_user_id IS NULL are processed without Microsoft access only.

-- ── mail_alert_rules — add owner_user_id ─────────────────────────────────────
ALTER TABLE mail_alert_rules
  ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES users(id);

-- ── user_notifications ────────────────────────────────────────────────────────
-- In-app notifications shown as banners in the frontend.
-- One active notification per type per user (UPSERT on conflict).
CREATE TABLE IF NOT EXISTS user_notifications (
  id          UUID      PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  tenant_id   UUID      NOT NULL,
  type        VARCHAR   NOT NULL,
  -- 'token_expired' | 'token_reconnected' | 'report_failed' | 'security_alert'
  message     TEXT      NOT NULL,
  action_url  TEXT,           -- where to go to resolve
  is_read     BOOLEAN   NOT NULL DEFAULT FALSE,
  created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
  UNIQUE (user_id, type)      -- one active notification per type per user
);

CREATE INDEX IF NOT EXISTS idx_notifications_user
  ON user_notifications (user_id, is_read);

-- ── Audit view ────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_task_execution_audit AS
SELECT
  t.id,
  t.tenant_id,
  t.owner_user_id,
  u_owner.email       AS owner_email,
  t.triggered_by,
  t.triggered_by_user_id,
  u_trigger.email     AS triggered_by_email,
  t.task_type,
  t.used_microsoft_token,
  t.token_owner_user_id,
  -- Flag any mismatch between token owner and task owner (should never happen)
  (t.token_owner_user_id IS NOT NULL
   AND t.token_owner_user_id != t.owner_user_id) AS token_owner_mismatch,
  t.status,
  t.error_detail,
  t.result_summary,
  t.started_at,
  t.completed_at,
  EXTRACT(EPOCH FROM (t.completed_at - t.started_at))::INT AS duration_seconds
FROM task_execution_log t
LEFT JOIN users u_owner   ON u_owner.id   = t.owner_user_id
LEFT JOIN users u_trigger ON u_trigger.id = t.triggered_by_user_id;

COMMIT;
