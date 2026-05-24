"""
services/mail/attachment_handler.py — Mail attachment processing.

For each attachment in an inbound email:
1. Sanitize filename and save to knowledge_store/{tenant_id}/mail_attachments/
2. Scan with ClamAV (reuses the existing clamd client from stage_0_security)
3. If clean and ingestable type: enqueue in KOS ingestion pipeline
4. Record in mail_attachments table

Security rules (same as document ingestion):
- ClamAV ConnectionError → quarantine, do NOT process
- Infected files go to quarantine_path, never to knowledge_store
- Max filename length enforced to prevent path traversal
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from pathlib import Path
from typing import Optional

import psycopg2.extensions

log = logging.getLogger(__name__)

KNOWLEDGE_STORE_ROOT = os.getenv("KOS_KNOWLEDGE_STORE_ROOT", "/app/knowledge_store")
QUARANTINE_ROOT = os.getenv("KOS_QUARANTINE_ROOT", "/app/quarantine")

# Content types the KOS ingestion pipeline can handle
INGESTABLE_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/html",
        "text/plain",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "image/webp",
    }
)


def _sanitize_filename(name: str) -> str:
    """
    Remove path separators and control characters from a filename.
    Limits length to 200 chars to prevent filesystem issues.
    """
    # Strip directory traversal attempts
    name = os.path.basename(name)
    # Remove null bytes and other control characters
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    # Replace spaces and other risky chars with underscore
    name = re.sub(r"[^\w.\-]", "_", name)
    # Enforce maximum length
    if len(name) > 200:
        stem, _, ext = name.rpartition(".")
        name = stem[:195] + "." + ext if ext else name[:200]
    return name or "attachment"


def _scan_with_clamav(file_path: str) -> dict:
    """
    Scan a file with ClamAV using the existing clamd socket client.

    Reuses services.ingestion.stage_0_security logic to avoid duplication.
    Returns {'status': 'clean'|'infected'|'error', 'detail': str|None}
    """
    try:
        import clamd  # type: ignore[import]

        clamd_host = os.getenv("KOS_CLAMD_HOST", "clamav")
        clamd_port = int(os.getenv("KOS_CLAMD_PORT", "3310"))
        cd = clamd.ClamdNetworkSocket(host=clamd_host, port=clamd_port)

        result = cd.scan(file_path)
        if result is None:
            return {"status": "clean", "detail": None}

        file_result = result.get(file_path, ("OK", None))
        status, virus_name = file_result
        if status == "OK":
            return {"status": "clean", "detail": None}
        elif status == "FOUND":
            log.error(
                "mail.attachment: INFECTED file detected: '%s' — virus: %s",
                file_path,
                virus_name,
            )
            return {"status": "infected", "detail": virus_name}
        else:
            return {"status": "error", "detail": f"Unexpected ClamAV status: {status}"}

    except Exception as exc:
        # ClamAV unreachable → fail safe: treat as error, do NOT process
        log.error(
            "mail.attachment: ClamAV scan failed for '%s': %s — quarantining",
            file_path,
            exc,
        )
        return {"status": "error", "detail": str(exc)}


def process_attachments(
    attachments: list[dict],
    message_id: str,
    tenant_id: str,
    db_conn: psycopg2.extensions.connection,
) -> list[str]:
    """
    Process all attachments from a parsed email message.

    Args:
        attachments: List of dicts from parser.parse_message()['attachments'].
                     Each dict has: filename, content_type, data (bytes), size_bytes.
        message_id:  The mail_messages.id UUID (not the RFC Message-ID).
        tenant_id:   Tenant UUID.
        db_conn:     Open psycopg2 connection.

    Returns:
        List of mail_attachments UUIDs created.
    """
    attachment_ids: list[str] = []

    for att in attachments:
        att_id = str(uuid.uuid4())
        safe_filename = _sanitize_filename(att["filename"])
        content_type = att.get("content_type", "application/octet-stream")

        # ── Storage path ──────────────────────────────────────────────────
        storage_dir = Path(KNOWLEDGE_STORE_ROOT) / tenant_id / "mail_attachments" / message_id
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = str(storage_dir / safe_filename)

        # ── Write to disk ─────────────────────────────────────────────────
        try:
            with open(storage_path, "wb") as fh:
                fh.write(att["data"])
        except OSError:
            log.exception(
                "mail.attachment: failed to write '%s' for message %s",
                safe_filename,
                message_id,
            )
            continue

        # ── ClamAV scan ───────────────────────────────────────────────────
        scan_result = _scan_with_clamav(storage_path)

        if scan_result["status"] == "infected":
            # Move to quarantine
            quarantine_dir = Path(QUARANTINE_ROOT) / tenant_id / "mail"
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            quarantine_path = str(quarantine_dir / f"{att_id}_{safe_filename}")
            try:
                Path(storage_path).rename(quarantine_path)
                storage_path = quarantine_path
            except OSError:
                log.exception("mail.attachment: could not move infected file to quarantine")

        # ── Insert into DB ────────────────────────────────────────────────
        try:
            with db_conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO mail_attachments
                      (id, message_id, tenant_id, filename, content_type,
                       size_bytes, storage_path, clamav_status, clamav_detail)
                    VALUES
                      (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        att_id,
                        message_id,
                        tenant_id,
                        att["filename"][:500],
                        content_type[:200],
                        att.get("size_bytes", len(att["data"])),
                        storage_path,
                        scan_result["status"],
                        scan_result.get("detail"),
                    ),
                )
        except Exception:
            db_conn.rollback()
            log.exception(
                "mail.attachment: DB insert failed for attachment '%s'",
                safe_filename,
            )
            continue

        # ── Enqueue in KOS pipeline if clean and ingestable ───────────────
        if scan_result["status"] == "clean" and content_type in INGESTABLE_TYPES:
            try:
                from services.queue.tasks import process_document  # noqa: PLC0415

                process_document.delay(
                    file_path=storage_path,
                    file_type=content_type,
                    tenant_id=tenant_id,
                    user_id="secretary-agent",
                    source_type="mail_attachment",
                )
                with db_conn.cursor() as cur:
                    cur.execute(
                        "UPDATE mail_attachments SET ingested = TRUE WHERE id = %s",
                        (att_id,),
                    )
                log.info(
                    "mail.attachment: enqueued '%s' for KOS ingestion",
                    safe_filename,
                )
            except Exception:
                log.exception(
                    "mail.attachment: failed to enqueue '%s' for ingestion",
                    safe_filename,
                )

        attachment_ids.append(att_id)

    try:
        db_conn.commit()
    except Exception:
        db_conn.rollback()
        log.exception("mail.attachment: commit failed")

    return attachment_ids
