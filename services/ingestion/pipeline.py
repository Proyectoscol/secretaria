"""
KOS Ingestion Pipeline — orchestrator.

Runs Stage 0 → 1 → 2 → 3 in sequence.
Stage 0 failures (security) are definitive; stages 1–2 are retried by Celery.

Usage (direct / testing):
    from services.ingestion.pipeline import run_pipeline
    result = run_pipeline(file_path, file_type, tenant_id, user_id,
                          source_type, db_conn, queue_job_id)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .stage_0_security import run_security_checks
from .stage_1_extraction import extract_structure
from .stage_2_canonicalize import canonicalize_and_store
from .stage_3_verify import verify_and_log

log = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    success: bool
    document_id: Optional[str] = None
    stage_failed: Optional[str] = None  # '0_security' | '1_extraction' | '2_canonicalize' | '3_verify'
    error: Optional[str] = None
    is_duplicate: bool = False


def run_pipeline(
    file_path: str,
    file_type: str,
    tenant_id: str,
    user_id: str,
    source_type: str,
    db_conn,                        # PEP-249 connection
    queue_job_id: str = "",
    source_id: Optional[str] = None,
    session_id: str = "",
    *,
    skip_clamav: bool = False,      # for integration tests
) -> PipelineResult:
    """
    Full ingestion pipeline for a single file.

    Returns a PipelineResult. Never raises — exceptions are caught and
    reported in the result.

    Stage 0 failures are definitive (security rejection).
    Stage 1-2 failures are transient — Celery will retry.
    """
    path = Path(file_path)
    log.info(
        "Pipeline START  file=%s  type=%s  tenant=%s  job=%s",
        path.name, file_type, tenant_id[:8], queue_job_id,
    )

    # Mark job as processing
    _update_queue_status(db_conn, queue_job_id, "processing")

    # ── Stage 0: Security ──────────────────────────────────────────────────────
    try:
        sec = run_security_checks(
            file_path, tenant_id, db_conn, skip_clamav=skip_clamav
        )
    except Exception as exc:
        return _fail(db_conn, queue_job_id, "0_security", str(exc))

    if not sec.passed:
        # Duplicate — not an error, just skip re-processing
        if sec.duplicate_document_id:
            log.info("Duplicate detected, returning existing doc %s",
                     sec.duplicate_document_id)
            _update_queue_status(db_conn, queue_job_id, "done")
            return PipelineResult(
                success=True,
                document_id=sec.duplicate_document_id,
                is_duplicate=True,
            )
        # Genuine security rejection
        _update_queue_status(db_conn, queue_job_id, "failed",
                             error_detail=sec.rejection_reason)
        return PipelineResult(
            success=False,
            stage_failed="0_security",
            error=sec.rejection_reason,
        )

    # ── Stage 1: Extraction ───────────────────────────────────────────────────
    try:
        extracted = extract_structure(file_path, file_type)
    except Exception as exc:
        log.exception("Stage 1 extraction failed for %s", path.name)
        return _fail(db_conn, queue_job_id, "1_extraction", str(exc))

    # ── Stage 2: Canonicalization ─────────────────────────────────────────────
    try:
        doc_id = canonicalize_and_store(
            extracted,
            tenant_id=tenant_id,
            file_hash=sec.file_hash,
            filename_original=path.name,
            file_type=file_type,
            source_id=source_id,
            db_conn=db_conn,
        )
    except Exception as exc:
        log.exception("Stage 2 canonicalize failed for %s", path.name)
        return _fail(db_conn, queue_job_id, "2_canonicalize", str(exc))

    # ── Stage 3: Verification ─────────────────────────────────────────────────
    try:
        verify_result = verify_and_log(
            document_id=doc_id,
            tenant_id=tenant_id,
            filename_original=path.name,
            queue_job_id=queue_job_id,
            db_conn=db_conn,
            session_id=session_id,
            user_id=user_id,
        )
    except Exception as exc:
        log.exception("Stage 3 verify failed for %s", path.name)
        # Non-fatal: document is stored even if verification step errors
        return PipelineResult(success=True, document_id=doc_id,
                              stage_failed="3_verify", error=str(exc))

    if not verify_result.ok:
        return PipelineResult(
            success=False,
            document_id=doc_id,
            stage_failed="3_verify",
            error=verify_result.failure_reason,
        )

    log.info("Pipeline DONE  doc_id=%s  file=%s", doc_id, path.name)
    return PipelineResult(success=True, document_id=doc_id)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fail(db_conn, queue_job_id: str, stage: str, error: str) -> PipelineResult:
    _update_queue_status(db_conn, queue_job_id, "failed", error_detail=error)
    return PipelineResult(success=False, stage_failed=stage, error=error)


def _update_queue_status(
    db_conn,
    job_id: str,
    status: str,
    *,
    error_detail: Optional[str] = None,
) -> None:
    if not job_id:
        return
    try:
        with db_conn.cursor() as cur:
            if status == "processing":
                cur.execute(
                    "UPDATE ingestion_queue SET status = 'processing', started_at = NOW() "
                    "WHERE id = %s",
                    (job_id,),
                )
            else:
                cur.execute(
                    "UPDATE ingestion_queue "
                    "SET status = %s, completed_at = NOW(), error_detail = %s "
                    "WHERE id = %s",
                    (status, error_detail, job_id),
                )
        db_conn.commit()
    except Exception as exc:
        log.error("Queue status update error: %s", exc)
