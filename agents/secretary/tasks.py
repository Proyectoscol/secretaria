"""
agents/secretary/tasks.py — Celery tasks for the Secretary agent.

All tasks that may use Microsoft tokens carry explicit owner_user_id.
Never enqueue a task without owner_user_id — see scheduler.py.
"""

from __future__ import annotations

import logging
import os

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
    owner_user_id: str,
    report_type: str,
    recipients: list,
    schedule_id: str = "",
) -> dict:
    """
    Generate and send a scheduled report on behalf of `owner_user_id`.

    owner_user_id is mandatory — it is the user who configured the schedule
    and whose Microsoft token is used if the report requires Microsoft access.
    The cron scheduler never calls this without an explicit owner.
    """
    from services.execution_context import ExecutionContext, execution_context  # noqa: PLC0415
    from services.microsoft.token_manager import TokenExpiredError, TokenNotFoundError  # noqa: PLC0415
    from agents.secretary.secretary import SecretaryAgent  # noqa: PLC0415

    ctx = ExecutionContext(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        triggered_by="scheduled",
        triggered_by_user_id="system",
        task_type="send_report",
        task_detail={"report_type": report_type, "schedule_id": schedule_id},
    )

    db_conn = _get_db()
    try:
        with execution_context(ctx, db_conn) as exec_ctx:
            agent = SecretaryAgent()
            result = agent.send_scheduled_report(tenant_id, report_type, recipients)

            # Update schedule last_execution_id
            if ctx.execution_log_id and schedule_id:
                with db_conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE mail_report_schedules
                        SET last_execution_id = %s::uuid
                        WHERE id = %s::uuid AND tenant_id = %s::uuid
                        """,
                        (ctx.execution_log_id, schedule_id, tenant_id),
                    )
                db_conn.commit()

            return result or {"status": "ok"}

    except (TokenExpiredError, TokenNotFoundError) as exc:
        # User was already notified by execution_context — do NOT retry.
        # Retrying with an expired token would just spam the notification.
        log.warning(
            "tasks: send_report skipped (token issue) | owner=%s type=%s: %s",
            owner_user_id, report_type, exc,
        )
        return {"status": "token_error", "owner_user_id": owner_user_id}

    except Exception as exc:
        log.exception(
            "tasks: send_scheduled_report_task failed | type=%s tenant=%s owner=%s",
            report_type, tenant_id, owner_user_id,
        )
        raise self.retry(exc=exc)

    finally:
        db_conn.close()
