"""
Stage 3 — Verification and notification.

Validates the output of stage 2, updates DB status, emits a user notification
via OpenClaw's internal webhook/WebSocket endpoint.

Zero LLM calls.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

KNOWLEDGE_STORE_ROOT = Path(os.getenv("KOS_KNOWLEDGE_STORE_ROOT", "/app/knowledge_store"))
OPENCLAW_NOTIFY_URL = os.getenv(
    "KOS_OPENCLAW_NOTIFY_URL", "http://openclaw:3000/internal/kos/notify"
)


@dataclass
class VerificationResult:
    ok: bool
    document_id: str
    checks: dict
    failure_reason: str = ""


def verify_and_log(
    document_id: str,
    tenant_id: str,
    filename_original: str,
    queue_job_id: str,
    db_conn,
    *,
    session_id: str = "",
    user_id: str = "",
) -> VerificationResult:
    """
    Run quality gates, update DB, notify the user.
    Always returns a result — never raises.
    """
    checks: dict = {}
    failures: list[str] = []

    # ── 3.1  Quality gates ─────────────────────────────────────────────────────
    canonical_dir = KNOWLEDGE_STORE_ROOT / tenant_id / document_id

    # Gate A: at least one text chunk exists in DB
    chunk_count = _count_chunks(db_conn, document_id, tenant_id)
    checks["chunk_count"] = chunk_count
    if chunk_count == 0:
        failures.append("no_chunks_extracted")

    # Gate B: canonical.md exists on disk
    md_path = canonical_dir / "canonical.md"
    checks["canonical_md_exists"] = md_path.exists()
    if not md_path.exists():
        failures.append("canonical_md_missing")

    # Gate C: metadata has title
    has_title = _check_title(db_conn, document_id)
    checks["has_title"] = has_title
    if not has_title:
        failures.append("metadata_missing_title")

    # Gate D: all chunks have embeddings
    unembedded = _count_unembedded_chunks(db_conn, document_id, tenant_id)
    checks["unembedded_chunks"] = unembedded
    if unembedded > 0:
        failures.append(f"{unembedded}_chunks_missing_embeddings")

    success = len(failures) == 0
    failure_reason = ", ".join(failures) if failures else ""

    # ── 3.2  Update DB status ─────────────────────────────────────────────────
    new_status = "done" if success else "failed"
    _update_document_status(db_conn, document_id, new_status)
    _update_queue_job(db_conn, queue_job_id, new_status,
                      failure_reason if not success else None)

    # ── 3.3  Notify user via OpenClaw internal webhook ────────────────────────
    if success:
        message = f"✓ Documento '**{filename_original}**' procesado y disponible en tu biblioteca."
    else:
        message = (
            f"⚠ No fue posible procesar '**{filename_original}**'. "
            f"Razón: {failure_reason}"
        )

    _notify_user(session_id=session_id, user_id=user_id,
                 tenant_id=tenant_id, message=message)

    # ── 3.4  Log in librarian_queries ─────────────────────────────────────────
    _log_librarian_event(
        db_conn, tenant_id=tenant_id, session_id=session_id,
        document_id=document_id, filename=filename_original,
        chunk_count=chunk_count, success=success,
    )

    result = VerificationResult(
        ok=success,
        document_id=document_id,
        checks=checks,
        failure_reason=failure_reason,
    )

    if success:
        log.info("Document %s verified OK (%d chunks)", document_id, chunk_count)
    else:
        log.error("Document %s verification FAILED: %s", document_id, failure_reason)

    return result


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _count_chunks(db_conn, document_id: str, tenant_id: str) -> int:
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM document_chunks "
                "WHERE document_id = %s AND tenant_id = %s",
                (document_id, tenant_id),
            )
            return cur.fetchone()[0]
    except Exception as exc:
        log.error("count_chunks error: %s", exc)
        return 0


def _count_unembedded_chunks(db_conn, document_id: str, tenant_id: str) -> int:
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM document_chunks "
                "WHERE document_id = %s AND tenant_id = %s AND embedding IS NULL",
                (document_id, tenant_id),
            )
            return cur.fetchone()[0]
    except Exception as exc:
        log.error("count_unembedded_chunks error: %s", exc)
        return 0


def _check_title(db_conn, document_id: str) -> bool:
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT title FROM document_metadata WHERE document_id = %s LIMIT 1",
                (document_id,),
            )
            row = cur.fetchone()
            return bool(row and row[0])
    except Exception as exc:
        log.error("check_title error: %s", exc)
        return False


def _update_document_status(db_conn, document_id: str, status: str) -> None:
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "UPDATE documents SET processing_status = %s, processed_at = NOW() "
                "WHERE id = %s",
                (status, document_id),
            )
        db_conn.commit()
    except Exception as exc:
        log.error("update_document_status error: %s", exc)


def _update_queue_job(db_conn, job_id: str, status: str, error_detail=None) -> None:
    if not job_id:
        return
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_queue "
                "SET status = %s, completed_at = NOW(), error_detail = %s "
                "WHERE id = %s",
                (status, error_detail, job_id),
            )
        db_conn.commit()
    except Exception as exc:
        log.error("update_queue_job error: %s", exc)


def _log_librarian_event(
    db_conn,
    tenant_id: str,
    session_id: str,
    document_id: str,
    filename: str,
    chunk_count: int,
    success: bool,
) -> None:
    try:
        import uuid  # noqa: PLC0415

        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO librarian_queries
                    (id, tenant_id, session_id, requested_by, original_query,
                     sources_searched, results_found, sources_used, confidence_score)
                VALUES (%s, %s, %s, 'ingestion_pipeline', %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid.uuid4()),
                    tenant_id,
                    session_id or None,
                    f"ingest:{filename}",
                    json.dumps(["ingestion_pipeline"]),
                    chunk_count if success else 0,
                    json.dumps([{"document_id": document_id}]),
                    1.0 if success else 0.0,
                ),
            )
        db_conn.commit()
    except Exception as exc:
        log.warning("librarian_queries log error: %s", exc)


# ── Notification ───────────────────────────────────────────────────────────────

def _notify_user(
    *,
    session_id: str,
    user_id: str,
    tenant_id: str,
    message: str,
) -> None:
    """
    POST notification to OpenClaw's internal notify endpoint.
    Fire-and-forget — failure is logged, not raised.
    """
    payload = json.dumps({
        "session_id": session_id,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "message": message,
        "source": "kos_ingestion",
    }).encode()

    try:
        req = urllib.request.Request(
            OPENCLAW_NOTIFY_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5):
            pass
        log.debug("User notification sent to %s", OPENCLAW_NOTIFY_URL)
    except Exception as exc:
        log.warning("Could not notify user (non-fatal): %s", exc)
