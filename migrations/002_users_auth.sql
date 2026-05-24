-- ============================================================
-- Users, Auth & Microsoft Platform Tokens
-- Prisma-compatible schema — mirrors prisma/schema.prisma
-- ============================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Tenants ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
  id         UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
  domain     TEXT        NOT NULL UNIQUE,
  name       TEXT        NOT NULL,
  created_at TIMESTAMP   NOT NULL DEFAULT NOW()
);

-- Users ────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
  id                 UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id          UUID        NOT NULL REFERENCES tenants(id),
  email              VARCHAR(255) NOT NULL UNIQUE,
  full_name          TEXT        NOT NULL,
  password_hash      TEXT,                         -- NULL for Microsoft-only users
  source             VARCHAR(16) NOT NULL DEFAULT 'local'
                         CHECK (source IN ('local','microsoft')),
  microsoft_auth_oid TEXT,                         -- Azure AD object ID
  avatar_url         TEXT,
  role               VARCHAR(16) NOT NULL DEFAULT 'user'
                         CHECK (role IN ('user','admin')),
  is_active          BOOLEAN     NOT NULL DEFAULT TRUE,
  email_verified     TIMESTAMP,
  created_at         TIMESTAMP   NOT NULL DEFAULT NOW(),
  last_login_at      TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_tenant ON users (tenant_id);
CREATE INDEX IF NOT EXISTS idx_users_email   ON users (email);

-- NextAuth accounts (OAuth providers) ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS accounts (
  id                  TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type                TEXT NOT NULL,
  provider            TEXT NOT NULL,
  provider_account_id TEXT NOT NULL,
  refresh_token       TEXT,
  access_token        TEXT,
  expires_at          INTEGER,
  token_type          TEXT,
  scope               TEXT,
  id_token            TEXT,
  session_state       TEXT,
  UNIQUE (provider, provider_account_id)
);

-- NextAuth sessions ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
  id            TEXT      PRIMARY KEY DEFAULT gen_random_uuid()::text,
  session_token TEXT      NOT NULL UNIQUE,
  user_id       UUID      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires       TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id);

-- NextAuth verification tokens ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS verification_tokens (
  identifier TEXT      NOT NULL,
  token      TEXT      NOT NULL UNIQUE,
  expires    TIMESTAMP NOT NULL,
  PRIMARY KEY (identifier, token)
);

-- Microsoft App 2 — encrypted platform tokens ─────────────────────────────────
CREATE TABLE IF NOT EXISTS microsoft_platform_tokens (
  id                      UUID      PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id                 UUID      NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  encrypted_access_token  TEXT      NOT NULL,   -- AES-256-GCM encrypted
  encrypted_refresh_token TEXT      NOT NULL,   -- AES-256-GCM encrypted
  token_expires_at        TIMESTAMP NOT NULL,
  scopes_granted          TEXT[]    NOT NULL DEFAULT '{}',
  connected_at            TIMESTAMP NOT NULL DEFAULT NOW(),
  last_refreshed_at       TIMESTAMP,
  microsoft_user_id       TEXT
);

COMMIT;
