"""
agents/secretary/tasks.py — Celery tasks for the Secretary agent.
"""

from __future__ import annotations

import logging

from services.queue.celery_app import app

log = logging.getLogger(__name__)


@app.task(
    name="agents.secretary.tasks.send_scheduled_report_task",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    queue="kos",
)
def send_scheduled_report_task(
    self,
    tenant_id: str,
    report_type: str,
    recipients: list,
) -> dict:
    """Celery wrapper around SecretaryAgent.send_scheduled_report."""
    try:
        from agents.secretary.secretary import SecretaryAgent  # noqa: PLC0415

        agent = SecretaryAgent()
        return agent.send_scheduled_report(tenant_id, report_type, recipients)
    except Exception as exc:
        log.exception(
            "secretary.tasks: send_scheduled_report_task failed (type=%s, tenant=%s)",
            report_type,
            tenant_id,
        )
        raise self.retry(exc=exc)
