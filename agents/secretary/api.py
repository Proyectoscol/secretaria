"""
agents/secretary/api.py — Internal REST endpoints for the Secretary agent.

Mounted at /internal/secretary/* by the Librarian API process.
All endpoints are internal; never expose to the public internet.

Endpoints:
  POST /internal/secretary/send           — manual send trigger
  GET  /internal/secretary/inbox          — recent inbound messages
  GET  /internal/secretary/threads        — thread list with pagination
  GET  /internal/secretary/threads/{id}   — single thread with messages
  POST /internal/secretary/whitelist      — add authorized domain
  DELETE /internal/secretary/whitelist/{domain} — remove authorized domain
  GET  /internal/secretary/accounts       — list mail accounts
  POST /internal/secretary/accounts       — create mail account
  GET  /internal/secretary/schedules      — report schedules
  PUT  /internal/secretary/schedules/{type} — update schedule config
  GET  /internal/secretary/alert-rules    — alert rules
  POST /internal/secretary/alert-rules    — create alert rule
"""

from __future__ import annotations

# ── Env validation must be first — before any network/DB imports ──────────────
from services.config.env_validator import validate_env
validate_env("kos", "mail")

import json
import logging
import os
from typing import Optional

import psycopg2
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

log = logging.getLogger(__name__)

DB_DSN = os.getenv("KOS_DB_DSN", "postgresql://openclaw:openclaw@postgres:5432/openclaw")

secretary_app = FastAPI(title="KOS Secretary Internal API", docs_url=None, redoc_url=None)


def _db():
    return psycopg2.connect(DB_DSN)


def _require_tenant(x_tenant_id: Optional[str]) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return x_tenant_id


# ── Models ────────────────────────────────────────────────────────────────────

class SendRequest(BaseModel):
    to_addresses: list[str]
    subject: str
    body_html: str
    body_text: Optional[str] = None
    cc_addresses: Optional[list[str]] = None
    reply_to: Optional[str] = None
    in_reply_to: Optional[str] = None
    trigger_type: str = "manual"

class WhitelistAddRequest(BaseModel):
    domain: str
    description: Optional[str] = None

class MailAccountRequest(BaseModel):
    email_address: str
    display_name: str
    mailbox_path: str

class ScheduleUpdateRequest(BaseModel):
    is_active: bool
    hour_utc: int
    minute_utc: int
    recipients: list[str]
    day_of_week: Optional[int] = None

class AlertRuleRequest(BaseModel):
    rule_name: str
    metric_key: str
    threshold_pct: float
    comparison_period: str = "week"
    recipients: list[str]
    min_interval_hours: int = 4


class DismissNotificationRequest(BaseModel):
    notification_type: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@secretary_app.post("/internal/secretary/send")
def send_email(
    req: SendRequest,
    x_tenant_id: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
):
    """Manually trigger an outbound email from the Secretary."""
    tenant_id = _require_tenant(x_tenant_id)
    from_address = os.getenv("MAIL_SECRETARIO_ADDRESS", "")
    if not from_address:
        raise HTTPException(status_code=503, detail="MAIL_SECRETARIO_ADDRESS not configured")

    from services.mail.sender import send_mail  # noqa: PLC0415

    db_conn = _db()
    try:
        result = send_mail(
            from_address=from_address,
            to_addresses=req.to_addresses,
            subject=req.subject,
            body_html=req.body_html,
            body_text=req.body_text,
            cc_addresses=req.cc_addresses,
            reply_to=req.reply_to,
            in_reply_to=req.in_reply_to,
            tenant_id=tenant_id,
            trigger_type=req.trigger_type,
            trigger_detail={"requested_by": x_user_id},
            db_conn=db_conn,
        )
        if not result["success"]:
            raise HTTPException(status_code=500, detail=result.get("error"))
        return result
    finally:
        db_conn.close()


@secretary_app.get("/internal/secretary/inbox")
def get_inbox(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    x_tenant_id: Optional[str] = Header(default=None),
):
    """List recent inbound messages with thread context."""
    tenant_id = _require_tenant(x_tenant_id)
    db_conn = _db()
    try:
        with db_conn.cursor() as cur:
            filters = ["m.tenant_id = %s", "m.direction = 'inbound'", "m.is_authorized = TRUE"]
            params: list = [tenant_id]
            if status:
                filters.append("m.processing_status = %s")
                params.append(status)

            where = " AND ".join(filters)
            cur.execute(
                f"""
                SELECT m.id, m.thread_id, m.from_address, m.from_name,
                       m.subject, m.snippet, m.received_at,
                       m.ai_classification, m.ai_priority, m.processing_status,
                       t.message_count
                FROM mail_messages m
                LEFT JOIN mail_threads t ON m.thread_id = t.id
                WHERE {where}
                ORDER BY m.received_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            rows = cur.fetchall()

        messages = [
            {
                "id": str(r[0]),
                "thread_id": str(r[1]) if r[1] else None,
                "from_address": r[2],
                "from_name": r[3],
                "subject": r[4],
                "snippet": r[5],
                "received_at": r[6].isoformat() if r[6] else None,
                "ai_classification": r[7],
                "ai_priority": r[8],
                "processing_status": r[9],
                "thread_message_count": r[10],
            }
            for r in rows
        ]
        return {"messages": messages, "count": len(messages), "offset": offset}
    finally:
        db_conn.close()


@secretary_app.get("/internal/secretary/threads")
def list_threads(
    limit: int = 50,
    offset: int = 0,
    x_tenant_id: Optional[str] = Header(default=None),
):
    """List email threads for the tenant."""
    tenant_id = _require_tenant(x_tenant_id)
    db_conn = _db()
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, thread_key, subject, participants,
                       first_message_at, last_message_at, message_count, status, ai_summary
                FROM mail_threads
                WHERE tenant_id = %s
                ORDER BY last_message_at DESC NULLS LAST
                LIMIT %s OFFSET %s
                """,
                (tenant_id, limit, offset),
            )
            rows = cur.fetchall()

        threads = [
            {
                "id": str(r[0]),
                "thread_key": r[1],
                "subject": r[2],
                "participants": r[3],
                "first_message_at": r[4].isoformat() if r[4] else None,
                "last_message_at": r[5].isoformat() if r[5] else None,
                "message_count": r[6],
                "status": r[7],
                "ai_summary": r[8],
            }
            for r in rows
        ]
        return {"threads": threads, "count": len(threads)}
    finally:
        db_conn.close()


@secretary_app.get("/internal/secretary/threads/{thread_id}")
def get_thread(
    thread_id: str,
    x_tenant_id: Optional[str] = Header(default=None),
):
    """Get a single thread with all its messages in chronological order."""
    tenant_id = _require_tenant(x_tenant_id)
    db_conn = _db()
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT id, subject, participants, first_message_at, last_message_at, message_count, status, ai_summary FROM mail_threads WHERE id = %s AND tenant_id = %s",
                (thread_id, tenant_id),
            )
            t = cur.fetchone()
            if not t:
                raise HTTPException(status_code=404, detail="Thread not found")

            cur.execute(
                """
                SELECT id, from_address, from_name, subject, body_sanitized,
                       body_text, snippet, received_at, direction,
                       ai_classification, ai_priority, ai_action_taken
                FROM mail_messages
                WHERE thread_id = %s AND tenant_id = %s
                ORDER BY received_at ASC
                """,
                (thread_id, tenant_id),
            )
            msgs = cur.fetchall()

        return {
            "thread": {
                "id": str(t[0]),
                "subject": t[1],
                "participants": t[2],
                "first_message_at": t[3].isoformat() if t[3] else None,
                "last_message_at": t[4].isoformat() if t[4] else None,
                "message_count": t[5],
                "status": t[6],
                "ai_summary": t[7],
            },
            "messages": [
                {
                    "id": str(m[0]),
                    "from_address": m[1],
                    "from_name": m[2],
                    "subject": m[3],
                    "body": m[4] or m[5],  # sanitized HTML or plain text
                    "snippet": m[6],
                    "received_at": m[7].isoformat() if m[7] else None,
                    "direction": m[8],
                    "ai_classification": m[9],
                    "ai_priority": m[10],
                    "ai_action_taken": m[11],
                }
                for m in msgs
            ],
        }
    finally:
        db_conn.close()


@secretary_app.post("/internal/secretary/whitelist")
def add_whitelist_domain(
    req: WhitelistAddRequest,
    x_tenant_id: Optional[str] = Header(default=None),
):
    """Add a domain to the authorized senders whitelist."""
    tenant_id = _require_tenant(x_tenant_id)
    db_conn = _db()
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mail_authorized_domains (tenant_id, domain, description)
                VALUES (%s, %s, %s)
                ON CONFLICT (tenant_id, domain) DO UPDATE SET is_active = TRUE, description = EXCLUDED.description
                RETURNING id
                """,
                (tenant_id, req.domain.lower().strip(), req.description),
            )
            row = cur.fetchone()
        db_conn.commit()
        return {"id": str(row[0]), "domain": req.domain}
    except Exception as exc:
        db_conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        db_conn.close()


@secretary_app.delete("/internal/secretary/whitelist/{domain}")
def remove_whitelist_domain(
    domain: str,
    x_tenant_id: Optional[str] = Header(default=None),
):
    """Deactivate a domain from the whitelist (soft delete)."""
    tenant_id = _require_tenant(x_tenant_id)
    db_conn = _db()
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "UPDATE mail_authorized_domains SET is_active = FALSE WHERE tenant_id = %s AND domain = %s",
                (tenant_id, domain.lower()),
            )
        db_conn.commit()
        return {"removed": domain}
    finally:
        db_conn.close()


@secretary_app.get("/internal/secretary/accounts")
def list_accounts(x_tenant_id: Optional[str] = Header(default=None)):
    """List all mail accounts for the tenant."""
    tenant_id = _require_tenant(x_tenant_id)
    db_conn = _db()
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT id, email_address, display_name, mailbox_path, is_active, created_at FROM mail_accounts WHERE tenant_id = %s ORDER BY created_at",
                (tenant_id,),
            )
            rows = cur.fetchall()
        return {
            "accounts": [
                {"id": str(r[0]), "email_address": r[1], "display_name": r[2], "mailbox_path": r[3], "is_active": r[4], "created_at": r[5].isoformat() if r[5] else None}
                for r in rows
            ]
        }
    finally:
        db_conn.close()


@secretary_app.put("/internal/secretary/schedules/{report_type}")
def update_schedule(
    report_type: str,
    req: ScheduleUpdateRequest,
    x_tenant_id: Optional[str] = Header(default=None),
):
    """Create or update a report schedule for the tenant."""
    tenant_id = _require_tenant(x_tenant_id)
    if report_type not in ("daily_summary", "weekly_metrics", "monthly_analysis"):
        raise HTTPException(status_code=400, detail="Invalid report_type")

    db_conn = _db()
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mail_report_schedules
                  (tenant_id, report_type, is_active, hour_utc, minute_utc, recipients, day_of_week)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                ON CONFLICT (tenant_id, report_type) DO UPDATE
                  SET is_active = EXCLUDED.is_active,
                      hour_utc = EXCLUDED.hour_utc,
                      minute_utc = EXCLUDED.minute_utc,
                      recipients = EXCLUDED.recipients,
                      day_of_week = EXCLUDED.day_of_week
                """,
                (
                    tenant_id,
                    report_type,
                    req.is_active,
                    req.hour_utc,
                    req.minute_utc,
                    json.dumps(req.recipients),
                    req.day_of_week,
                ),
            )
        db_conn.commit()
        return {"updated": report_type}
    except Exception as exc:
        db_conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        db_conn.close()


@secretary_app.get("/internal/secretary/schedules")
def get_schedules(x_tenant_id: Optional[str] = Header(default=None)):
    """List report schedules for the tenant."""
    tenant_id = _require_tenant(x_tenant_id)
    db_conn = _db()
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT report_type, is_active, hour_utc, minute_utc, recipients, day_of_week, last_sent_at FROM mail_report_schedules WHERE tenant_id = %s ORDER BY report_type",
                (tenant_id,),
            )
            rows = cur.fetchall()
        return {
            "schedules": [
                {
                    "report_type": r[0], "is_active": r[1], "hour_utc": r[2],
                    "minute_utc": r[3], "recipients": r[4], "day_of_week": r[5],
                    "last_sent_at": r[6].isoformat() if r[6] else None,
                }
                for r in rows
            ]
        }
    finally:
        db_conn.close()


# ── Notifications endpoints ───────────────────────────────────────────────────

@secretary_app.get("/internal/secretary/notifications/unread")
def get_unread_notifications(
    x_tenant_id: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
):
    """
    Return unread notifications for the requesting user.

    Used by the TokenExpiryBanner to poll for token_expired notifications.
    Returns only notifications belonging to the requesting user (from the
    session), never for other users — enforced by WHERE user_id = %s.
    """
    tenant_id = _require_tenant(x_tenant_id)
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    db_conn = _db()
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, type, payload, created_at
                FROM user_notifications
                WHERE user_id = %s
                  AND tenant_id = %s
                  AND dismissed_at IS NULL
                ORDER BY created_at DESC
                """,
                (x_user_id, tenant_id),
            )
            rows = cur.fetchall()
        return {
            "notifications": [
                {
                    "id": str(r[0]),
                    "type": r[1],
                    "payload": r[2],
                    "created_at": r[3].isoformat() if r[3] else None,
                }
                for r in rows
            ]
        }
    finally:
        db_conn.close()


@secretary_app.post("/internal/secretary/notifications/dismiss")
def dismiss_notification(
    req: DismissNotificationRequest,
    x_tenant_id: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
):
    """
    Mark a notification type as dismissed for the requesting user.

    Sets dismissed_at so it no longer appears in unread.
    Uses UPDATE WHERE user_id = %s — a user can only dismiss their own
    notifications; no cross-user modification is possible.
    """
    tenant_id = _require_tenant(x_tenant_id)
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    db_conn = _db()
    try:
        import datetime  # noqa: PLC0415
        with db_conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_notifications
                SET dismissed_at = %s
                WHERE user_id = %s
                  AND tenant_id = %s
                  AND type = %s
                  AND dismissed_at IS NULL
                """,
                (datetime.datetime.utcnow(), x_user_id, tenant_id, req.notification_type),
            )
        db_conn.commit()
        return {"dismissed": req.notification_type}
    except Exception as exc:
        db_conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        db_conn.close()


# ── Health check endpoint (admin only) ────────────────────────────────────────

@secretary_app.get("/internal/secretary/health")
def system_health(
    x_tenant_id: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
):
    """
    Return the health of all KOS infrastructure services.

    Admin-only: the proxy injects X-User-ID; we verify role='admin' in the DB.
    Non-admins receive 403 — no infrastructure data is leaked.
    """
    import time  # noqa: PLC0415
    tenant_id = _require_tenant(x_tenant_id)

    # ── Admin role check ───────────────────────────────────────────────────
    db_conn = _db()
    try:
        if not x_user_id:
            raise HTTPException(status_code=403, detail="Admin access required")

        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT role FROM users
                WHERE id = %s AND tenant_id = %s
                """,
                (x_user_id, tenant_id),
            )
            row = cur.fetchone()

        if not row or row[0] != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
    except HTTPException:
        raise
    except Exception:
        log.exception("health: admin check failed")
        raise HTTPException(status_code=500, detail="Health check unavailable")
    finally:
        db_conn.close()

    # ── Probe services ─────────────────────────────────────────────────────
    services: list[dict] = []

    def _probe(name: str, fn) -> dict:
        start = time.monotonic()
        try:
            detail = fn()
            latency_ms = round((time.monotonic() - start) * 1000)
            return {
                "name": name, "status": "healthy",
                "latency_ms": latency_ms,
                "detail": detail,
                "checked_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            }
        except Exception as exc:
            latency_ms = round((time.monotonic() - start) * 1000)
            return {
                "name": name, "status": "unhealthy",
                "latency_ms": latency_ms,
                "detail": str(exc)[:200],
                "checked_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            }

    # PostgreSQL
    def _probe_postgres():
        conn = _db()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        finally:
            conn.close()
        return None

    # Redis
    def _probe_redis():
        import redis  # noqa: PLC0415
        r = redis.from_url(os.getenv("KOS_REDIS_URL", "redis://redis:6379/0"), socket_timeout=3)
        r.ping()
        return None

    # ClamAV
    def _probe_clamav():
        import clamd  # noqa: PLC0415
        host = os.getenv("KOS_CLAMD_HOST", "clamav")
        port = int(os.getenv("KOS_CLAMD_PORT", "3310"))
        c = clamd.ClamdNetworkSocket(host, port, timeout=5)
        c.ping()
        return None

    # Librarian API
    def _probe_librarian():
        import httpx  # noqa: PLC0415
        url = os.getenv("LIBRARIAN_API_URL", "http://librarian_api:8001")
        r = httpx.get(f"{url}/internal/librarian/health", timeout=5.0)
        r.raise_for_status()
        return None

    # Celery/Redis queue depth
    def _probe_celery():
        import redis  # noqa: PLC0415
        r = redis.from_url(os.getenv("KOS_REDIS_URL", "redis://redis:6379/0"), socket_timeout=3)
        depth = r.llen("kos")
        return f"queue depth: {depth}"

    # SMTP
    def _probe_smtp():
        import smtplib  # noqa: PLC0415
        host = os.getenv("MAIL_SMTP_HOST", "postfix")
        port = int(os.getenv("MAIL_SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=5):
            pass
        return None

    # Langfuse
    def _probe_langfuse():
        import httpx  # noqa: PLC0415
        host = os.getenv("LANGFUSE_HOST", "http://langfuse:3000")
        r = httpx.get(f"{host}/api/public/health", timeout=5.0)
        r.raise_for_status()
        return None

    probes = [
        ("postgres",  _probe_postgres),
        ("redis",     _probe_redis),
        ("clamav",    _probe_clamav),
        ("librarian", _probe_librarian),
        ("celery",    _probe_celery),
        ("smtp",      _probe_smtp),
        ("langfuse",  _probe_langfuse),
    ]

    for name, fn in probes:
        services.append(_probe(name, fn))

    # Determine overall status
    statuses = {s["status"] for s in services}
    if "unhealthy" in statuses:
        overall = "unhealthy" if any(
            s["name"] in ("postgres", "redis") and s["status"] == "unhealthy"
            for s in services
        ) else "degraded"
    elif "degraded" in statuses:
        overall = "degraded"
    else:
        overall = "healthy"

    import datetime  # noqa: PLC0415
    return {
        "overall": overall,
        "checked_at": datetime.datetime.utcnow().isoformat() + "Z",
        "services": services,
        "version": "1.0.0",
    }
