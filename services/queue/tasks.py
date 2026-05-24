"""
KOS Celery tasks.

process_document      — full pipeline for a single file
generate_embeddings_batch — standalone batch embedding (used for re-indexing)
sync_onedrive_metadata    — refresh last_modified for cached OneDrive files
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import psycopg2

from .celery_app import app

log = logging.getLogger(__name__)

DB_DSN: str = os.getenv(
    "KOS_DB_DSN",
    "postgresql://openclaw:openclaw@postgres:5432/openclaw",
)


def _get_db():
    """Open a new psycopg2 connection per task invocation."""
    conn = psycopg2.connect(DB_DSN)
    # Register pgvector type so LIST → vector cast works transparently
    try:
        from pgvector.psycopg2 import register_vector  # noqa: PLC0415
        register_vector(conn)
    except ImportError:
        pass  # pgvector Python adapter is optional; raw list cast still works
    return conn


# ── Task: process_document ────────────────────────────────────────────────────

@app.task(
    bind=True,
    name="kos.process_document",
    max_retries=3,
    default_retry_delay=30,         # seconds; Celery doubles on each retry
)
def process_document(
    self,
    file_path: str,
    file_type: str,
    tenant_id: str,
    user_id: str,
    source_type: str,
    queue_job_id: str = "",
    source_id: Optional[str] = None,
    session_id: str = "",
    skip_clamav: bool = False,
) -> dict:
    """
    Full ingestion pipeline for one file.

    Security failures (Stage 0) → no retry.
    Extraction / canonicalization failures → retry up to 3 times.
    """
    from services.ingestion.pipeline import run_pipeline  # noqa: PLC0415

    db_conn = _get_db()
    try:
        result = run_pipeline(
            file_path=file_path,
            file_type=file_type,
            tenant_id=tenant_id,
            user_id=user_id,
            source_type=source_type,
            db_conn=db_conn,
            queue_job_id=queue_job_id,
            source_id=source_id,
            session_id=session_id,
            skip_clamav=skip_clamav,
        )
    except Exception as exc:
        db_conn.rollback()
        log.exception("Unhandled pipeline exception for job %s", queue_job_id)
        # Don't retry Stage 0 rejections; retry everything else.
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))
    finally:
        db_conn.close()

    if not result.success:
        stage = result.stage_failed or "unknown"
        # Security failures are definitive — do not retry
        if stage == "0_security":
            log.error("Security rejection for job %s: %s", queue_job_id, result.error)
            return {"success": False, "stage": stage, "error": result.error}

        # Other stages: raise to trigger Celery retry
        raise self.retry(
            exc=RuntimeError(f"Stage {stage} failed: {result.error}"),
            countdown=30 * (2 ** self.request.retries),
        )

    return {
        "success": True,
        "document_id": result.document_id,
        "is_duplicate": result.is_duplicate,
    }


# ── Task: generate_embeddings_batch ──────────────────────────────────────────

@app.task(
    name="kos.generate_embeddings_batch",
    max_retries=2,
)
def generate_embeddings_batch(chunk_ids: list[str], tenant_id: str) -> dict:
    """
    (Re-)generate embeddings for a list of chunk UUIDs.

    Used for bulk re-indexing or when embeddings were skipped during ingest.
    Processes in batches of EMBEDDING_BATCH_SIZE to cap RAM usage.
    """
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    embedding_model = os.getenv(
        "KOS_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    )
    batch_size = int(os.getenv("KOS_EMBEDDING_BATCH_SIZE", "32"))

    encoder = SentenceTransformer(embedding_model)
    db_conn = _get_db()

    updated = 0
    try:
        for batch_start in range(0, len(chunk_ids), batch_size):
            batch = chunk_ids[batch_start: batch_start + batch_size]

            with db_conn.cursor() as cur:
                # Fetch texts for this batch
                cur.execute(
                    "SELECT id, content_text FROM document_chunks "
                    "WHERE id = ANY(%s) AND tenant_id = %s",
                    (batch, tenant_id),
                )
                rows = cur.fetchall()

            if not rows:
                continue

            ids = [r[0] for r in rows]
            texts = [r[1] for r in rows]
            vectors = encoder.encode(
                texts, normalize_embeddings=True, show_progress_bar=False
            )

            with db_conn.cursor() as cur:
                for chunk_id, vec in zip(ids, vectors):
                    cur.execute(
                        "UPDATE document_chunks SET embedding = %s::vector WHERE id = %s",
                        (vec.tolist(), chunk_id),
                    )
            db_conn.commit()
            updated += len(ids)

    finally:
        db_conn.close()

    log.info("generate_embeddings_batch: updated %d/%d chunks", updated, len(chunk_ids))
    return {"updated": updated, "total": len(chunk_ids)}


# ── Task: sync_onedrive_metadata ──────────────────────────────────────────────

@app.task(
    name="kos.sync_onedrive_metadata",
    max_retries=2,
)
def sync_onedrive_metadata(
    tenant_id: str,
    user_id: str,
    file_ids: list[str],
    microsoft_token: str,
) -> dict:
    """
    For each OneDrive file_id, call Graph API and update last_modified_onedrive.
    Marks content_cached=False if the remote file changed since last ingest.

    microsoft_token must be a short-lived access token fetched by the caller.
    It is NOT stored; only used for this task invocation.
    """
    import urllib.request  # noqa: PLC0415
    import json            # noqa: PLC0415

    GRAPH_BASE = "https://graph.microsoft.com/v1.0"
    updated = 0
    db_conn = _get_db()

    try:
        with db_conn.cursor() as cur:
            for file_id in file_ids:
                try:
                    req = urllib.request.Request(
                        f"{GRAPH_BASE}/me/drive/items/{file_id}"
                        "?$select=id,name,lastModifiedDateTime",
                        headers={"Authorization": f"Bearer {microsoft_token}"},
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        item = json.loads(resp.read())

                    remote_modified = item.get("lastModifiedDateTime")

                    # If file changed, invalidate cache
                    cur.execute(
                        """
                        UPDATE onedrive_index
                        SET last_checked_at = NOW(),
                            last_modified_onedrive = %s,
                            content_cached = CASE
                                WHEN last_modified_onedrive < %s THEN FALSE
                                ELSE content_cached
                            END
                        WHERE onedrive_file_id = %s AND tenant_id = %s
                        """,
                        (remote_modified, remote_modified, file_id, tenant_id),
                    )
                    updated += 1
                except Exception as exc:
                    log.warning("sync_onedrive_metadata: failed for file %s: %s",
                                file_id, exc)

        db_conn.commit()
    finally:
        db_conn.close()

    return {"synced": updated, "total": len(file_ids)}
