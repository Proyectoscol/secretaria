"""
services/mail/sender.py — SMTP outbound mail via local Postfix.

Never calls external services. Routes through the Postfix container
on the Docker internal network (host: postfix, port: 587).

Thread-safe: creates a new SMTP connection per call.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import uuid
from datetime import datetime, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import psycopg2.extensions

log = logging.getLogger(__name__)

SMTP_HOST = os.getenv("MAIL_SMTP_HOST", "postfix")
SMTP_PORT = int(os.getenv("MAIL_SMTP_PORT", "587"))
SMTP_USER = os.getenv("MAIL_SECRETARIO_ADDRESS", "")
SMTP_PASS = os.getenv("MAIL_SECRETARIO_PASSWORD", "")

MAX_DAILY_OUTBOUND = int(os.getenv("MAIL_MAX_DAILY_OUTBOUND", "500"))


def _check_daily_limit(tenant_id: str, db_conn: psycopg2.extensions.connection) -> bool:
    """Return True if tenant is within the daily outbound limit."""
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM mail_outbound
                WHERE tenant_id = %s
                  AND status = 'sent'
                  AND sent_at >= NOW() - INTERVAL '24 hours'
                """,
                (tenant_id,),
            )
            count = cur.fetchone()[0]
        if count >= MAX_DAILY_OUTBOUND:
            log.warning(
                "mail.sender: daily outbound limit (%d) reached for tenant %s",
                MAX_DAILY_OUTBOUND,
                tenant_id,
            )
            return False
        return True
    except Exception:
        log.exception("mail.sender: failed to check daily limit")
        return False  # fail safe


def send_mail(
    from_address: str,
    to_addresses: list[str | dict],
    subject: str,
    body_html: str,
    body_text: Optional[str] = None,
    cc_addresses: Optional[list] = None,
    reply_to: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    attachments: Optional[list[dict]] = None,
    tenant_id: Optional[str] = None,
    trigger_type: str = "manual",
    trigger_detail: Optional[dict] = None,
    db_conn: Optional[psycopg2.extensions.connection] = None,
) -> dict:
    """
    Send an email via the local Postfix SMTP relay.

    Records the outbound attempt in mail_outbound before sending.

    Args:
        from_address:   Sender address (must match an active mail_account).
        to_addresses:   List of recipient addresses (strings or {email, name} dicts).
        subject:        Email subject.
        body_html:      HTML body (required).
        body_text:      Plain text alternative (optional but recommended).
        cc_addresses:   List of CC addresses.
        reply_to:       Reply-To header value.
        in_reply_to:    Message-ID of the email being replied to (for threading).
        attachments:    List of {filename, data: bytes, content_type} dicts.
        tenant_id:      Tenant UUID (required for outbound logging).
        trigger_type:   Why this email is being sent.
        trigger_detail: Additional context about the trigger.
        db_conn:        Database connection for logging. If None, logging is skipped.

    Returns:
        {'success': bool, 'message_id': str | None, 'error': str | None}
    """

    # ── Normalize recipient lists ─────────────────────────────────────────────
    def _normalize(lst: list) -> list[str]:
        result = []
        for item in lst or []:
            if isinstance(item, dict):
                result.append(item.get("email", ""))
            else:
                result.append(str(item))
        return [addr for addr in result if addr and "@" in addr]

    to_list = _normalize(to_addresses)
    cc_list = _normalize(cc_addresses or [])
    all_recipients = to_list + cc_list

    if not to_list:
        return {"success": False, "message_id": None, "error": "No valid recipients"}

    # ── Daily limit guard ─────────────────────────────────────────────────────
    if tenant_id and db_conn and not _check_daily_limit(tenant_id, db_conn):
        return {
            "success": False,
            "message_id": None,
            "error": f"Daily outbound limit ({MAX_DAILY_OUTBOUND}) reached",
        }

    # ── Build MIME message ────────────────────────────────────────────────────
    msg = MIMEMultipart("alternative")
    generated_message_id = f"<{uuid.uuid4()}@{from_address.split('@')[-1]}>"
    msg["Message-ID"] = generated_message_id
    msg["From"] = from_address
    msg["To"] = ", ".join(to_list)
    msg["Subject"] = subject
    msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")

    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    if reply_to:
        msg["Reply-To"] = reply_to
    if in_reply_to:
        msg["In-Reply-To"] = f"<{in_reply_to.strip('<>')}>"
        msg["References"] = f"<{in_reply_to.strip('<>')}>"

    # Auto-generated header (helps email clients and prevents abuse loops)
    msg["X-Mailer"] = "KOS-Secretario/1.0"
    msg["Auto-Submitted"] = "auto-generated"

    # Body parts (text first, then HTML — email clients show the last matching part)
    if body_text:
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    # Attachments
    for att in attachments or []:
        main_type, _, sub_type = att.get("content_type", "application/octet-stream").partition("/")
        part = MIMEBase(main_type, sub_type)
        part.set_payload(att["data"])
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{att["filename"]}"',
        )
        msg.attach(part)

    # ── Log to mail_outbound before sending ───────────────────────────────────
    outbound_id: Optional[str] = None
    if tenant_id and db_conn:
        outbound_id = str(uuid.uuid4())
        try:
            with db_conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO mail_outbound
                      (id, tenant_id, to_addresses, cc_addresses, subject,
                       body_html, body_text, trigger_type, trigger_detail,
                       status, smtp_message_id)
                    VALUES
                      (%s, %s, %s::jsonb, %s::jsonb, %s,
                       %s, %s, %s, %s::jsonb,
                       'sending', %s)
                    """,
                    (
                        outbound_id,
                        tenant_id,
                        json.dumps([{"email": a} for a in to_list]),
                        json.dumps([{"email": a} for a in cc_list]),
                        subject,
                        body_html,
                        body_text,
                        trigger_type,
                        json.dumps(trigger_detail or {}),
                        generated_message_id,
                    ),
                )
            db_conn.commit()
        except Exception:
            log.exception("mail.sender: failed to log outbound to DB")

    # ── Send via SMTP ─────────────────────────────────────────────────────────
    error: Optional[str] = None
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            if SMTP_USER and SMTP_PASS:
                smtp.login(SMTP_USER, SMTP_PASS)
            smtp.sendmail(from_address, all_recipients, msg.as_bytes())

        log.info(
            "mail.sender: sent '%s' from %s to %s (message_id=%s)",
            subject,
            from_address,
            to_list,
            generated_message_id,
        )

        if outbound_id and db_conn:
            with db_conn.cursor() as cur:
                cur.execute(
                    "UPDATE mail_outbound SET status = 'sent', sent_at = NOW() WHERE id = %s",
                    (outbound_id,),
                )
            db_conn.commit()

        return {"success": True, "message_id": generated_message_id, "error": None}

    except smtplib.SMTPException as exc:
        error = str(exc)
        log.error("mail.sender: SMTP error sending to %s: %s", to_list, exc)
    except OSError as exc:
        error = f"Connection error: {exc}"
        log.error("mail.sender: connection failed to %s:%d — %s", SMTP_HOST, SMTP_PORT, exc)

    # ── Update outbound record as failed ──────────────────────────────────────
    if outbound_id and db_conn:
        try:
            with db_conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE mail_outbound
                    SET status = 'failed', error_detail = %s,
                        retry_count = retry_count + 1
                    WHERE id = %s
                    """,
                    (error, outbound_id),
                )
            db_conn.commit()
        except Exception:
            log.exception("mail.sender: failed to update outbound status to failed")

    return {"success": False, "message_id": None, "error": error}
