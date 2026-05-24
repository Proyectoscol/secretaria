"""
agents/secretary/scheduler.py — Celery Beat schedule for the Secretary agent.

This module defines the periodic task schedule consumed by Celery Beat
(the `celery_beat` service in docker-compose.kos.yml).

Celery Beat is a separate process from the worker — both must run.
"""

from __future__ import annotations

import logging
import os

import psycopg2
from celery.schedules import crontab

from services.queue.celery_app import app

log = logging.getLogger(__name__)

DB_DSN = os.getenv("KOS_DB_DSN", "postgresql://openclaw:openclaw@postgres:5432/openclaw")

# ── Beat schedule ─────────────────────────────────────────────────────────────
# These are the static defaults. Per-tenant schedules in mail_report_schedules
# are handled by the dynamic scheduler task below.

app.conf.beat_schedule = {
    # ── Mail polling ──────────────────────────────────────────────────────────
    "poll-inbox": {
        "task": "services.mail.tasks.poll_all_inboxes",
        "schedule": float(os.getenv("MAIL_POLL_INTERVAL_SECONDS", "30")),
    },
    # ── Retry failed outbound messages every 15 minutes ───────────────────────
    "retry-outbound": {
        "task": "services.mail.tasks.send_queued_outbound",
        "schedule": 900.0,  # 15 minutes
    },
    # ── Daily reports — 7:00 AM UTC (adjust via MAIL_REPORT_TIMEZONE) ─────────
    "daily-reports": {
        "task": "agents.secretary.scheduler.send_all_daily_reports",
        "schedule": crontab(hour=7, minute=0),
    },
    # ── Weekly reports — Monday 8:00 AM UTC ───────────────────────────────────
    "weekly-reports": {
        "task": "agents.secretary.scheduler.send_all_weekly_reports",
        "schedule": crontab(hour=8, minute=0, day_of_week=1),
    },
    # ── Monthly reports — 1st of month 8:30 AM UTC ────────────────────────────
    "monthly-reports": {
        "task": "agents.secretary.scheduler.send_all_monthly_reports",
        "schedule": crontab(hour=8, minute=30, day_of_month=1),
    },
    # ── Anomaly check — every hour ────────────────────────────────────────────
    "anomaly-check": {
        "task": "agents.secretary.scheduler.check_all_anomalies",
        "schedule": crontab(minute=0),
    },
}

app.conf.timezone = os.getenv("MAIL_REPORT_TIMEZONE", "America/Bogota")


# ── Tasks dispatched by Beat ──────────────────────────────────────────────────

def _get_db():
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False
    return conn


@app.task(name="agents.secretary.scheduler.send_all_daily_reports", queue="kos")
def send_all_daily_reports() -> dict:
    """Send daily summary reports to all configured tenants."""
    return _dispatch_reports("daily_summary")


@app.task(name="agents.secretary.scheduler.send_all_weekly_reports", queue="kos")
def send_all_weekly_reports() -> dict:
    """Send weekly metrics reports to all configured tenants."""
    return _dispatch_reports("weekly_metrics")


@app.task(name="agents.secretary.scheduler.send_all_monthly_reports", queue="kos")
def send_all_monthly_reports() -> dict:
    """Send monthly analysis reports to all configured tenants."""
    return _dispatch_reports("monthly_analysis")


def _dispatch_reports(report_type: str) -> dict:
    """Query active report schedules and dispatch per-tenant report tasks."""
    from agents.secretary.tasks import send_scheduled_report_task  # noqa: PLC0415

    db_conn = _get_db()
    dispatched = 0
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT tenant_id, recipients FROM mail_report_schedules
                WHERE report_type = %s AND is_active = TRUE
                """,
                (report_type,),
            )
            rows = cur.fetchall()

        for row in rows:
            tenant_id, recipients = str(row[0]), row[1] or []
            send_scheduled_report_task.delay(
                tenant_id=tenant_id,
                report_type=report_type,
                recipients=recipients,
            )
            dispatched += 1

        log.info("scheduler: dispatched %d %s tasks", dispatched, report_type)
        return {"dispatched": dispatched, "report_type": report_type}

    except Exception:
        log.exception("scheduler: error dispatching %s reports", report_type)
        return {"dispatched": 0, "error": "dispatch_failed"}
    finally:
        db_conn.close()


@app.task(name="agents.secretary.scheduler.check_all_anomalies", queue="kos")
def check_all_anomalies() -> dict:
    """
    Run anomaly detection for all active tenants.

    In production, metric_data is populated from MCP-connected data sources.
    This stub calls detect_and_alert with empty metric_data — hook in real
    data sources by populating metric_data from MCP tool responses.
    """
    from agents.secretary.secretary import SecretaryAgent  # noqa: PLC0415

    db_conn = _get_db()
    checked = 0
    try:
        with db_conn.cursor() as cur:
            cur.execute("SELECT DISTINCT tenant_id FROM mail_alert_rules WHERE is_active = TRUE")
            tenants = [str(row[0]) for row in cur.fetchall()]

        agent = SecretaryAgent()
        for tenant_id in tenants:
            # TODO: populate metric_data from configured MCP data sources
            metric_data: dict = {}
            agent.detect_and_alert(tenant_id, metric_data)
            checked += 1

        return {"tenants_checked": checked}
    except Exception:
        log.exception("scheduler: check_all_anomalies error")
        return {"tenants_checked": checked, "error": "partial_failure"}
    finally:
        db_conn.close()
