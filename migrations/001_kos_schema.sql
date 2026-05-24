-- ============================================================
-- KOS (Knowledge Operating System) — Schema v1
-- PostgreSQL + pgvector required
-- ============================================================

BEGIN;

-- ── Enable required extensions ────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm"; -- trigram for ILIKE-index on filename

-- ============================================================
-- knowledge_sources
-- Master registry of every knowledge source in the system.
-- ============================================================
CREATE TABLE IF NOT EXISTS knowledge_sources (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID        NOT NULL,
    source_type     VARCHAR(32) NOT NULL
                        CHECK (source_type IN ('local_upload','onedrive','mcp_database','sharepoint')),
    source_ref      TEXT,                       -- local path, OneDrive file_id, DB name
    display_name    TEXT,
    owner_user_id   UUID,
    first_seen_at   TIMESTAMP   NOT NULL DEFAULT NOW(),
    last_accessed_at TIMESTAMP,
    access_count    INTEGER     NOT NULL DEFAULT 0,
    index_status    VARCHAR(16) NOT NULL DEFAULT 'not_indexed'
                        CHECK (index_status IN ('not_indexed','partial','full'))
);

CREATE INDEX IF NOT EXISTS idx_knowledge_sources_tenant
    ON knowledge_sources (tenant_id);

-- ============================================================
-- documents
-- Documents that have passed through the full ingestion pipeline.
-- ============================================================
CREATE TABLE IF NOT EXISTS documents (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id           UUID        REFERENCES knowledge_sources(id) ON DELETE SET NULL,
    tenant_id           UUID        NOT NULL,
    hash_sha256         VARCHAR(64) NOT NULL,       -- global dedup key
    filename_original   TEXT,
    file_type           VARCHAR(16)
                            CHECK (file_type IN ('pdf','docx','xlsx','pptx','html','image')),
    page_count          INTEGER,
    language_detected   VARCHAR(8),
    processing_status   VARCHAR(16) NOT NULL DEFAULT 'pending'
                            CHECK (processing_status IN
                                ('pending','processing','done','failed','quarantined')),
    canonical_path      TEXT,                       -- /knowledge_store/{tenant}/{doc_id}/
    processed_at        TIMESTAMP,
    version_number      INTEGER     NOT NULL DEFAULT 1,
    security_scan_status VARCHAR(16)
                            CHECK (security_scan_status IN ('clean','suspicious','blocked')),
    security_scan_detail JSONB,
    created_at          TIMESTAMP   NOT NULL DEFAULT NOW()
);

-- hash is globally unique to prevent cross-tenant re-processing
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_hash
    ON documents (hash_sha256);
CREATE INDEX IF NOT EXISTS idx_documents_tenant_status
    ON documents (tenant_id, processing_status);
CREATE INDEX IF NOT EXISTS idx_documents_tenant
    ON documents (tenant_id);

-- ============================================================
-- document_metadata
-- Algorithmically-extracted metadata (no LLM).
-- ============================================================
CREATE TABLE IF NOT EXISTS document_metadata (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id     UUID        NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    title           TEXT,
    authors         JSONB,                          -- ["Alice", "Bob"]
    date_created    TIMESTAMP,
    date_modified   TIMESTAMP,
    organization    TEXT,
    keywords        JSONB,                          -- ["contract","NDA"]
    subject         TEXT,
    custom_fields   JSONB                           -- varies by file_type
);

CREATE INDEX IF NOT EXISTS idx_document_metadata_document
    ON document_metadata (document_id);

-- ============================================================
-- document_chunks
-- Semantic retrieval fragments with pgvector embeddings.
-- ============================================================
CREATE TABLE IF NOT EXISTS document_chunks (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id     UUID        NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tenant_id       UUID        NOT NULL,
    chunk_index     INTEGER     NOT NULL,
    section_title   TEXT,
    content_text    TEXT        NOT NULL,
    content_type    VARCHAR(20) NOT NULL DEFAULT 'text'
                        CHECK (content_type IN
                            ('text','table','figure_caption','header','list')),
    embedding       vector(768),                    -- all-MiniLM-L6-v2 output dim
    page_number     INTEGER,
    char_start      INTEGER,
    char_end        INTEGER
);

-- HNSW index: fast approximate nearest-neighbour for cosine similarity
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- GIN index: PostgreSQL full-text search
CREATE INDEX IF NOT EXISTS idx_chunks_fts
    ON document_chunks USING gin (to_tsvector('simple', content_text));

-- Composite index for tenant-scoped lookups
CREATE INDEX IF NOT EXISTS idx_chunks_tenant_document
    ON document_chunks (tenant_id, document_id);

-- ============================================================
-- document_figures
-- Extracted images / charts from documents.
-- ============================================================
CREATE TABLE IF NOT EXISTS document_figures (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id     UUID        NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    figure_index    INTEGER     NOT NULL,
    caption         TEXT,
    image_path      TEXT,                           -- /knowledge_store/.../figures/fig_NNN.png
    page_number     INTEGER,
    ocr_text        TEXT                            -- NULL unless OCR was applied
);

CREATE INDEX IF NOT EXISTS idx_figures_document
    ON document_figures (document_id);

-- ============================================================
-- onedrive_index
-- On-demand index of OneDrive files.
-- Rows are created ONLY when a file is first requested.
-- ============================================================
CREATE TABLE IF NOT EXISTS onedrive_index (
    id                      UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id               UUID        NOT NULL,
    user_id                 UUID        NOT NULL,
    onedrive_file_id        TEXT        NOT NULL UNIQUE, -- immutable Microsoft Graph ID
    filename                TEXT,
    file_type               VARCHAR(16),
    size_bytes              BIGINT,
    last_modified_onedrive  TIMESTAMP,
    weburl                  TEXT,
    folder_path             TEXT,
    first_indexed_at        TIMESTAMP   NOT NULL DEFAULT NOW(),
    last_checked_at         TIMESTAMP,
    content_cached          BOOLEAN     NOT NULL DEFAULT FALSE,
    summary_cache           TEXT,
    embedding_cache         vector(768),
    document_id             UUID        REFERENCES documents(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_onedrive_tenant_user
    ON onedrive_index (tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_onedrive_filename_trgm
    ON onedrive_index USING gin (filename gin_trgm_ops); -- fast ILIKE

-- ============================================================
-- mcp_sources
-- External databases accessible via MCP protocol.
-- credentials_vault_ref is a reference only — NEVER raw creds.
-- ============================================================
CREATE TABLE IF NOT EXISTS mcp_sources (
    id                      UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id               UUID        NOT NULL,
    name                    TEXT        NOT NULL,       -- "CRM Clientes"
    mcp_endpoint            TEXT        NOT NULL,
    schema_snapshot         JSONB,                      -- table/field descriptions
    last_schema_sync        TIMESTAMP,
    credentials_vault_ref   TEXT        NOT NULL,       -- vault reference, not creds
    query_examples          JSONB,                      -- guide the Librarian agent
    is_active               BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mcp_sources_tenant
    ON mcp_sources (tenant_id, is_active);

-- ============================================================
-- mcp_query_log
-- Audit log of every query sent to an external MCP source.
-- ============================================================
CREATE TABLE IF NOT EXISTS mcp_query_log (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id           UUID        NOT NULL REFERENCES mcp_sources(id),
    tenant_id           UUID        NOT NULL,
    query_executed      TEXT,
    result_summary      TEXT,
    executed_at         TIMESTAMP   NOT NULL DEFAULT NOW(),
    requested_by        VARCHAR(64),                    -- 'user', 'librarian_agent', etc.
    cached_result       JSONB,
    response_time_ms    INTEGER
);

CREATE INDEX IF NOT EXISTS idx_mcp_query_log_tenant
    ON mcp_query_log (tenant_id, executed_at DESC);

-- ============================================================
-- librarian_queries
-- Full audit log of everything the Librarian agent processes.
-- ============================================================
CREATE TABLE IF NOT EXISTS librarian_queries (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID        NOT NULL,
    session_id          UUID,
    requested_by        VARCHAR(64),
    original_query      TEXT,
    sources_searched    JSONB,                          -- ordered array of sources tried
    results_found       INTEGER     NOT NULL DEFAULT 0,
    sources_used        JSONB,                          -- where the final answer came from
    confidence_score    FLOAT,
    response_time_ms    INTEGER,
    created_at          TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_librarian_queries_tenant
    ON librarian_queries (tenant_id, created_at DESC);

-- For cache lookup: same tenant + recent + high confidence
CREATE INDEX IF NOT EXISTS idx_librarian_queries_cache
    ON librarian_queries (tenant_id, created_at DESC)
    WHERE confidence_score > 0.8;

-- ============================================================
-- ingestion_queue
-- Celery-backed job queue for document processing.
-- ============================================================
CREATE TABLE IF NOT EXISTS ingestion_queue (
    id                      UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id               UUID        NOT NULL,
    file_path               TEXT        NOT NULL,
    file_type               VARCHAR(16),
    source_type             VARCHAR(32),
    requested_by_user_id    UUID,
    status                  VARCHAR(16) NOT NULL DEFAULT 'queued'
                                CHECK (status IN ('queued','processing','done','failed')),
    priority                INTEGER     NOT NULL DEFAULT 5,
    created_at              TIMESTAMP   NOT NULL DEFAULT NOW(),
    started_at              TIMESTAMP,
    completed_at            TIMESTAMP,
    error_detail            TEXT,
    retry_count             INTEGER     NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ingestion_queue_pending
    ON ingestion_queue (tenant_id, status, priority DESC, created_at)
    WHERE status IN ('queued','processing');

COMMIT;
