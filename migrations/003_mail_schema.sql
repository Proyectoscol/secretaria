-- ============================================================
-- KOS — Mail Schema v1 (Secretario IA)
-- PostgreSQL + pgvector required (pgvector for embedding column)
-- Apply after: 001_kos_schema.sql, 002_users_auth.sql
-- ============================================================

BEGIN;

-- ────────────────────────────────────────────────────────────────────────────
-- mail_accounts — buzones gestionados por el Secretario IA
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mail_accounts (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID        NOT NULL,
    email_address  VARCHAR(255) UNIQUE NOT NULL,    -- secretaria@empresa.com
    display_name   TEXT        NOT NULL,             -- "Secretaria IA — Empresa X"
    mailbox_path   TEXT        NOT NULL,             -- ruta interna en Dovecot
    is_active      BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mail_accounts_tenant
    ON mail_accounts(tenant_id);

-- ────────────────────────────────────────────────────────────────────────────
-- mail_authorized_domains — whitelist estricta de dominios autorizados
-- Solo se procesan correos provenientes de dominios en esta tabla.
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mail_authorized_domains (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID        NOT NULL,
    domain      VARCHAR(255) NOT NULL,   -- 'proyectoscall.com'
    description TEXT,                    -- 'Dominio corporativo principal'
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, domain)
);

CREATE INDEX IF NOT EXISTS idx_mail_authorized_domains_tenant
    ON mail_authorized_domains(tenant_id, is_active);

-- ────────────────────────────────────────────────────────────────────────────
-- mail_threads — hilos de conversación agrupados
-- Un hilo relaciona todos los correos con el mismo In-Reply-To / References.
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mail_threads (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID        NOT NULL,
    thread_key       TEXT        NOT NULL,    -- SHA-256[:32] del Message-ID raíz
    subject          TEXT        NOT NULL,
    participants     JSONB       NOT NULL DEFAULT '[]',  -- array de emails
    first_message_at TIMESTAMPTZ,
    last_message_at  TIMESTAMPTZ,
    message_count    INTEGER     NOT NULL DEFAULT 0,
    status           VARCHAR(16) NOT NULL DEFAULT 'active'
                         CHECK (status IN ('active', 'archived', 'processed')),
    ai_summary       TEXT,        -- resumen generado por el Secretario
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, thread_key)
);

CREATE INDEX IF NOT EXISTS idx_mail_threads_tenant
    ON mail_threads(tenant_id);
CREATE INDEX IF NOT EXISTS idx_mail_threads_last_message
    ON mail_threads(last_message_at DESC);

-- ────────────────────────────────────────────────────────────────────────────
-- mail_messages — correos individuales (entrantes y salientes)
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mail_messages (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID        NOT NULL,
    thread_id           UUID        REFERENCES mail_threads(id) ON DELETE CASCADE,
    mail_account_id     UUID        REFERENCES mail_accounts(id) ON DELETE SET NULL,

    -- ── Headers RFC 5322 ──────────────────────────────────────────────────
    message_id          TEXT        UNIQUE NOT NULL,  -- Message-ID del header
    in_reply_to         TEXT,                         -- Message-ID al que responde
    references_list     JSONB       NOT NULL DEFAULT '[]', -- cadena de Message-IDs

    -- ── Remitente y destinatarios ─────────────────────────────────────────
    from_address        TEXT        NOT NULL,
    from_name           TEXT,
    from_domain         TEXT        NOT NULL,   -- extraído de from_address
    to_addresses        JSONB       NOT NULL,   -- [{email, name}]
    cc_addresses        JSONB       NOT NULL DEFAULT '[]',
    bcc_addresses       JSONB       NOT NULL DEFAULT '[]',
    reply_to            TEXT,

    -- ── Contenido ─────────────────────────────────────────────────────────
    subject             TEXT        NOT NULL,
    body_text           TEXT,
    body_html           TEXT,
    body_sanitized      TEXT,       -- HTML sanitizado para renderizar en UI
    snippet             TEXT,       -- primeras 200 chars para preview

    -- ── Metadata técnica ──────────────────────────────────────────────────
    received_at         TIMESTAMPTZ NOT NULL,
    sent_at             TIMESTAMPTZ,
    raw_headers         JSONB,      -- todos los headers originales
    spam_score          FLOAT,      -- score de Rspamd (0-100)
    dkim_valid          BOOLEAN,
    spf_valid           BOOLEAN,

    -- ── Estado de procesamiento ───────────────────────────────────────────
    direction           VARCHAR(8)  NOT NULL
                            CHECK (direction IN ('inbound', 'outbound')),
    is_authorized       BOOLEAN     NOT NULL DEFAULT FALSE,
    processing_status   VARCHAR(16) NOT NULL DEFAULT 'pending'
                            CHECK (processing_status IN (
                                'pending', 'authorized', 'rejected',
                                'processing', 'processed', 'failed'
                            )),
    processing_error    TEXT,
    processed_at        TIMESTAMPTZ,

    -- ── Análisis IA ───────────────────────────────────────────────────────
    ai_classification   VARCHAR(32),
    -- 'report_request' | 'query' | 'alert_acknowledgment' | 'reply' | 'informational'
    ai_priority         VARCHAR(8),
    -- 'high' | 'medium' | 'low'
    ai_sentiment        VARCHAR(16),
    ai_summary          TEXT,
    ai_action_taken     TEXT,        -- descripción de la acción del Secretario
    embedding           vector(768), -- para búsqueda semántica futura

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mail_messages_tenant
    ON mail_messages(tenant_id);
CREATE INDEX IF NOT EXISTS idx_mail_messages_thread
    ON mail_messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_mail_messages_from_domain
    ON mail_messages(from_domain);
CREATE INDEX IF NOT EXISTS idx_mail_messages_status
    ON mail_messages(processing_status);
CREATE INDEX IF NOT EXISTS idx_mail_messages_received
    ON mail_messages(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_mail_messages_direction
    ON mail_messages(tenant_id, direction, received_at DESC);

-- Búsqueda fulltext en subject + body_text
CREATE INDEX IF NOT EXISTS idx_mail_messages_fts
    ON mail_messages
    USING GIN(to_tsvector('spanish', coalesce(subject,'') || ' ' || coalesce(body_text,'')));

-- Búsqueda semántica en embeddings
CREATE INDEX IF NOT EXISTS idx_mail_messages_embedding
    ON mail_messages
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ────────────────────────────────────────────────────────────────────────────
-- mail_attachments — adjuntos de correos entrantes
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mail_attachments (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id      UUID        NOT NULL REFERENCES mail_messages(id) ON DELETE CASCADE,
    tenant_id       UUID        NOT NULL,

    filename        TEXT        NOT NULL,
    content_type    TEXT        NOT NULL,
    size_bytes      INTEGER     NOT NULL DEFAULT 0,
    storage_path    TEXT        NOT NULL,  -- ruta en knowledge_store

    -- ── Seguridad ─────────────────────────────────────────────────────────
    clamav_status   VARCHAR(16) NOT NULL DEFAULT 'pending'
                        CHECK (clamav_status IN ('pending', 'clean', 'infected', 'error')),
    clamav_detail   TEXT,       -- nombre del virus si infectado

    -- ── Integración KOS ───────────────────────────────────────────────────
    document_id     UUID,       -- FK a documents si fue ingestado en KOS
    ingested        BOOLEAN     NOT NULL DEFAULT FALSE,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mail_attachments_message
    ON mail_attachments(message_id);
CREATE INDEX IF NOT EXISTS idx_mail_attachments_tenant
    ON mail_attachments(tenant_id);

-- ────────────────────────────────────────────────────────────────────────────
-- mail_outbound — registro de correos enviados por el Secretario
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mail_outbound (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID        NOT NULL,
    from_account_id  UUID        REFERENCES mail_accounts(id) ON DELETE SET NULL,

    to_addresses     JSONB       NOT NULL,   -- [{email, name}]
    cc_addresses     JSONB       NOT NULL DEFAULT '[]',
    subject          TEXT        NOT NULL,
    body_html        TEXT        NOT NULL,
    body_text        TEXT,

    -- ── Trigger del envío ─────────────────────────────────────────────────
    trigger_type     VARCHAR(32) NOT NULL,
    -- 'scheduled_report' | 'anomaly_alert' | 'reply' | 'manual' | 'analysis'
    trigger_detail   JSONB,      -- contexto del trigger (inbound_message_id, etc.)

    -- ── Estado ────────────────────────────────────────────────────────────
    status           VARCHAR(16) NOT NULL DEFAULT 'queued'
                         CHECK (status IN ('queued', 'sending', 'sent', 'failed')),
    smtp_message_id  TEXT,       -- Message-ID asignado al enviar
    sent_at          TIMESTAMPTZ,
    error_detail     TEXT,
    retry_count      INTEGER     NOT NULL DEFAULT 0,

    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mail_outbound_tenant
    ON mail_outbound(tenant_id);
CREATE INDEX IF NOT EXISTS idx_mail_outbound_status
    ON mail_outbound(status, created_at DESC);

-- ────────────────────────────────────────────────────────────────────────────
-- mail_report_schedules — configuración de reportes programados por tenant
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mail_report_schedules (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID        NOT NULL,
    report_type  VARCHAR(32) NOT NULL,
    -- 'daily_summary' | 'weekly_metrics' | 'monthly_analysis'
    is_active    BOOLEAN     NOT NULL DEFAULT TRUE,
    hour_utc     INTEGER     NOT NULL DEFAULT 7  CHECK (hour_utc BETWEEN 0 AND 23),
    minute_utc   INTEGER     NOT NULL DEFAULT 0  CHECK (minute_utc BETWEEN 0 AND 59),
    day_of_week  INTEGER,   -- NULL = diario; 0=lunes … 6=domingo
    recipients   JSONB       NOT NULL DEFAULT '[]',  -- array de emails
    last_sent_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, report_type)
);

-- ────────────────────────────────────────────────────────────────────────────
-- mail_alert_rules — reglas de detección de anomalías
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mail_alert_rules (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL,
    rule_name       TEXT        NOT NULL,
    metric_key      TEXT        NOT NULL,    -- ej: 'ventas_diarias'
    threshold_pct   FLOAT       NOT NULL,    -- ej: -20 = caída >20%
    comparison_period VARCHAR(16) NOT NULL DEFAULT 'week',
    -- 'day' | 'week' | 'month'
    recipients      JSONB       NOT NULL DEFAULT '[]',
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    min_interval_hours INTEGER  NOT NULL DEFAULT 4, -- no enviar más de 1 alerta cada N horas
    last_triggered_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mail_alert_rules_tenant
    ON mail_alert_rules(tenant_id, is_active);

COMMIT;
