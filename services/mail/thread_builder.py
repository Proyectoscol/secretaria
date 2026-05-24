"""
services/mail/thread_builder.py — Email thread construction and management.

Implements the threading algorithm described in RFC 5256:
1. If References is present: the first Message-ID is the thread root.
2. If only In-Reply-To: use it as the root.
3. If neither: this is a new root thread.

Forwards (Fwd:, FW:) start a new thread but retain the original Subject
for correlation (stripping common prefixes: Re:, Fwd:, FW:, AW:, RV:).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Optional

import psycopg2.extensions

log = logging.getLogger(__name__)

# Subject prefixes to strip when normalizing for thread matching
_SUBJECT_PREFIX_RE = re.compile(
    r"^\s*(re|fwd?|fw|aw|rv|[Rr]esp|[Aa]nt)[\s:\[].+?[:\]]\s*",
    re.IGNORECASE,
)


def _normalize_subject(subject: str) -> str:
    """Strip common reply/forward prefixes to get the canonical subject."""
    prev = None
    while prev != subject:
        prev = subject
        subject = _SUBJECT_PREFIX_RE.sub("", subject).strip()
    return subject


def upsert_thread(
    parsed_message: dict,
    tenant_id: str,
    db_conn: psycopg2.extensions.connection,
) -> str:
    """
    Create a new thread or update an existing one for this message.

    Returns the thread_id (UUID string) of the thread this message belongs to.

    Args:
        parsed_message: The dict returned by parser.parse_message().
        tenant_id:      The tenant this message belongs to.
        db_conn:        An open psycopg2 connection.
    """
    thread_key = parsed_message["thread_key"]
    from_address = parsed_message["from_address"]
    subject = parsed_message["subject"]
    received_at = parsed_message.get("received_at")

    try:
        with db_conn.cursor() as cur:
            # ── Check for existing thread ─────────────────────────────────
            cur.execute(
                """
                SELECT id, participants FROM mail_threads
                WHERE tenant_id = %s AND thread_key = %s
                FOR UPDATE
                """,
                (tenant_id, thread_key),
            )
            row = cur.fetchone()

            if row:
                thread_id = str(row[0])
                existing_participants: list = row[1] if row[1] else []

                # Merge new participants (deduplicate)
                if from_address not in existing_participants:
                    existing_participants.append(from_address)

                cur.execute(
                    """
                    UPDATE mail_threads
                    SET last_message_at = COALESCE(%s::timestamptz, NOW()),
                        message_count   = message_count + 1,
                        participants    = %s::jsonb,
                        updated_at      = NOW()
                    WHERE id = %s
                    """,
                    (
                        received_at,
                        json.dumps(existing_participants),
                        thread_id,
                    ),
                )
                log.info(
                    "mail.thread_builder: updated thread %s (%d messages)",
                    thread_id,
                    row[0],
                )
            else:
                # ── Create new thread ─────────────────────────────────────
                thread_id = str(uuid.uuid4())
                participants = [from_address]

                cur.execute(
                    """
                    INSERT INTO mail_threads
                      (id, tenant_id, thread_key, subject, participants,
                       first_message_at, last_message_at, message_count)
                    VALUES
                      (%s, %s, %s, %s, %s::jsonb,
                       COALESCE(%s::timestamptz, NOW()),
                       COALESCE(%s::timestamptz, NOW()),
                       1)
                    """,
                    (
                        thread_id,
                        tenant_id,
                        thread_key,
                        subject,
                        json.dumps(participants),
                        received_at,
                        received_at,
                    ),
                )
                log.info(
                    "mail.thread_builder: created thread %s — '%s'",
                    thread_id,
                    subject,
                )

        db_conn.commit()
        return thread_id

    except Exception:
        db_conn.rollback()
        log.exception(
            "mail.thread_builder: error upserting thread for key '%s', tenant %s",
            thread_key,
            tenant_id,
        )
        raise
