"""
services/mail/tasks.py — Celery tasks for mail processing.

Tasks:
  process_inbound_mail   — parse, whitelist-check, persist, classify one email
  poll_all_inboxes       — trigger IMAP poll for all active accounts (Beat)
  send_queued_outbound   — retry failed outbound messages
"""

from __future__ import annotations

import json
import logging
import os
import uuid

import psycopg2

from services.queue.celery_app import app

log = logging.getLogger(__name__)

DB_DSN: str = os.getenv(
    "KOS_DB_DSN",
    "postgresql://openclaw:openclaw@postgres:5432/openclaw",
)


def _get_db():
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False
    return conn


# ── Task: process_inbound_mail ────────────────────────────────────────────────

@app.task(
    name="services.mail.tasks.process_inbound_mail",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    queue="kos",
)
def process_inbound_mail(self, raw_email: bytes, imap_uid: str | None) -> dict:
    """
    Full pipeline for a single inbound email.

    Steps:
    1. Parse RFC 5322 message (parser.py)
    2. Determine recipient → find tenant_id
    3. Whitelist check: is from_domain authorized?
    4. Upsert thread
    5. Persist mail_messages record
    6. Process attachments (ClamAV + optional KOS ingestion)
    7. Classify with Secretary agent
    8. Mark as processed

    Args:
        raw_email: The raw email bytes.
        imap_uid:  The IMAP message UID, or None if delivered via Postfix pipe.
    """
    from services.mail.parser import parse_message
    from services.mail.whitelist import is_authorized, get_tenant_for_recipient
    from services.mail.thread_builder import upsert_thread
    from services.mail.attachment_handler import process_attachments

    db_conn = None
    try:
        parsed = parse_message(raw_email)

        log.info(
            "mail.tasks: processing message_id='%s' from='%s'",
            parsed["message_id"],
            parsed["from_address"],
        )

        # ── Determine tenant from recipient ───────────────────────────────
        db_conn = _get_db()

        # Find the first To address that matches a known mail_account
        tenant_id: str | None = None
        account_id: str | None = None
        for recipient in parsed["to_addresses"]:
            tenant_id = get_tenant_for_recipient(recipient["email"], db_conn)
            if tenant_id:
                # Get account ID
                with db_conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM mail_accounts WHERE email_address = %s AND is_active = TRUE",
                        (recipient["email"],),
                    )
                    row = cur.fetchone()
                    account_id = str(row[0]) if row else None
                break

        if not tenant_id:
            log.info(
                "mail.tasks: no tenant found for recipients %s — discarding",
                [r["email"] for r in parsed["to_addresses"]],
            )
            return {"status": "discarded", "reason": "no_tenant"}

        # ── Whitelist check ───────────────────────────────────────────────
        authorized = is_authorized(parsed["from_domain"], tenant_id, db_conn)

        # ── Upsert thread ─────────────────────────────────────────────────
        thread_id = upsert_thread(parsed, tenant_id, db_conn)

        # ── Persist mail_messages ─────────────────────────────────────────
        message_uuid = str(uuid.uuid4())
        processing_status = "authorized" if authorized else "rejected"

        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mail_messages (
                    id, tenant_id, thread_id, mail_account_id,
                    message_id, in_reply_to, references_list,
                    from_address, from_name, from_domain,
                    to_addresses, cc_addresses, bcc_addresses, reply_to,
                    subject, body_text, body_html, snippet,
                    received_at, raw_headers,
                    spam_score, dkim_valid, spf_valid,
                    direction, is_authorized, processing_status
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s::jsonb,
                    %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb, %s,
                    %s, %s, %s, %s,
                    %s::timestamptz, %s::jsonb,
                    %s, %s, %s,
                    'inbound', %s, %s
                )
                ON CONFLICT (message_id) DO NOTHING
                """,
                (
                    message_uuid,
                    tenant_id,
                    thread_id,
                    account_id,
                    parsed["message_id"],
                    parsed.get("in_reply_to"),
                    json.dumps(parsed.get("references_list", [])),
                    parsed["from_address"],
                    parsed.get("from_name"),
                    parsed["from_domain"],
                    json.dumps(parsed["to_addresses"]),
                    json.dumps(parsed.get("cc_addresses", [])),
                    json.dumps(parsed.get("bcc_addresses", [])),
                    parsed.get("reply_to"),
                    parsed["subject"],
                    parsed.get("body_text"),
                    parsed.get("body_html"),
                    parsed.get("snippet"),
                    parsed.get("received_at"),
                    json.dumps(parsed.get("raw_headers", {})),
                    parsed.get("spam_score"),
                    parsed.get("dkim_valid"),
                    parsed.get("spf_valid"),
                    authorized,
                    processing_status,
                ),
            )
        db_conn.commit()

        log.info(
            "mail.tasks: persisted message uuid=%s status=%s",
            message_uuid,
            processing_status,
        )

        # ── Process attachments (authorized only) ─────────────────────────
        if authorized and parsed.get("attachments"):
            process_attachments(
                parsed["attachments"],
                message_uuid,
                tenant_id,
                db_conn,
            )

        # ── Classify + respond (authorized only) ──────────────────────────
        # LLM classification runs in Celery (never in request time)
        if authorized:
            classify_and_respond.delay(message_uuid, tenant_id)

        return {
            "status": "ok",
            "message_uuid": message_uuid,
            "authorized": authorized,
            "thread_id": thread_id,
        }

    except Exception as exc:
        log.exception(
            "mail.tasks: unhandled error processing message (imap_uid=%s): %s",
            imap_uid,
            exc,
        )
        if db_conn:
            db_conn.rollback()
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
    finally:
        if db_conn:
            try:
                db_conn.close()
            except Exception:
                pass


# ── Task: classify_and_respond ────────────────────────────────────────────────

@app.task(
    name="services.mail.tasks.classify_and_respond",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    queue="kos",
)
def classify_and_respond(self, message_uuid: str, tenant_id: str) -> dict:
    """
    Classify an authorized inbound message and trigger the Secretary agent response.
    Runs after process_inbound_mail persists the message.
    """
    try:
        from agents.secretary.secretary import SecretaryAgent  # noqa: PLC0415

        agent = SecretaryAgent()
        result = agent.process_inbound_message(message_uuid, tenant_id)
        return result or {"status": "processed"}
    except Exception as exc:
        log.exception(
            "mail.tasks: classify_and_respond failed for message %s: %s",
            message_uuid,
            exc,
        )
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))


# ── Task: poll_all_inboxes ────────────────────────────────────────────────────

@app.task(
    name="services.mail.tasks.poll_all_inboxes",
    queue="kos",
)
def poll_all_inboxes() -> dict:
    """
    Triggered by Celery Beat every POLL_INTERVAL seconds.
    Runs one IMAP poll pass for all active mail accounts.
    """
    from services.mail.receiver import poll_inbox_once  # noqa: PLC0415
    import imaplib

    imap_host = os.getenv("MAIL_IMAP_HOST", "dovecot")
    imap_port = int(os.getenv("MAIL_IMAP_PORT", "993"))
    imap_user = os.getenv("MAIL_SECRETARIO_ADDRESS", "")
    imap_pass = os.getenv("MAIL_SECRETARIO_PASSWORD", "")

    if not imap_user or not imap_pass:
        log.warning("mail.tasks: IMAP credentials not configured — skipping poll")
        return {"status": "skipped", "reason": "no_credentials"}

    try:
        with imaplib.IMAP4_SSL(imap_host, imap_port) as imap:
            imap.login(imap_user, imap_pass)
            count = poll_inbox_once(imap)
        return {"status": "ok", "enqueued": count}
    except Exception as exc:
        log.error("mail.tasks: poll_all_inboxes error: %s", exc)
        return {"status": "error", "error": str(exc)}


# ── Task: send_queued_outbound ────────────────────────────────────────────────

@app.task(
    name="services.mail.tasks.send_queued_outbound",
    queue="kos",
)
def send_queued_outbound() -> dict:
    """
    Retry failed outbound messages (retry_count < 3, status = 'failed').
    Run by Celery Beat every 15 minutes.
    """
    from services.mail.sender import send_mail  # noqa: PLC0415

    db_conn = _get_db()
    sent = 0
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tenant_id, to_addresses, cc_addresses, subject,
                       body_html, body_text, smtp_message_id
                FROM mail_outbound
                WHERE status = 'failed' AND retry_count < 3
                ORDER BY created_at ASC
                LIMIT 20
                FOR UPDATE SKIP LOCKED
                """,
            )
            rows = cur.fetchall()

        for row in rows:
            outbound_id, tenant_id = str(row[0]), str(row[1])
            to_addresses = row[2] or []
            subject = row[4]
            body_html = row[5]
            body_text = row[6]

            result = send_mail(
                from_address=os.getenv("MAIL_SECRETARIO_ADDRESS", ""),
                to_addresses=to_addresses,
                subject=subject,
                body_html=body_html,
                body_text=body_text,
                tenant_id=tenant_id,
                trigger_type="retry",
                db_conn=db_conn,
            )
            if result["success"]:
                sent += 1

        return {"status": "ok", "sent": sent}
    except Exception:
        log.exception("mail.tasks: send_queued_outbound error")
        return {"status": "error"}
    finally:
        db_conn.close()
