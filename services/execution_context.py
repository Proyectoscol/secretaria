"""
services/execution_context.py — Execution context for every system operation.

Every task — manual, scheduled, webhook, system — MUST create an
ExecutionContext before running.  This guarantees:

  1. There is always an explicit owner_user_id.
  2. Microsoft tokens are always fetched for the owner, never for a
     different user (security invariant enforced by MicrosoftTokenManager).
  3. Every operation is recorded in task_execution_log.
  4. Token failures produce user-visible notifications, not silent errors.

Usage::

    from services.execution_context import ExecutionContext, execution_context

    ctx = ExecutionContext(
        tenant_id='uuid',
        owner_user_id='uuid-camilo',
        triggered_by='scheduled',
        triggered_by_user_id='system',
        task_type='send_report',
        task_detail={'schedule_id': 'uuid'},
    )

    with execution_context(ctx, db_conn) as exec_ctx:
        token = exec_ctx.get_microsoft_token()   # always Camilo's token
        # ... use token ...
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Optional

import psycopg2.extensions

from services.microsoft.token_manager import (
    MicrosoftTokenManager,
    TokenExpiredError,
    TokenInvalidError,
    TokenNotFoundError,
    SecurityViolationError,
)

log = logging.getLogger(__name__)


# ── Data class ────────────────────────────────────────────────────────────────


@dataclass
class ExecutionContext:
    tenant_id:            str
    owner_user_id:        str
    triggered_by:         str   # 'scheduled' | 'manual' | 'webhook' | 'system'
    triggered_by_user_id: str   # who fired it (may equal owner_user_id)
    task_type:            str
    task_detail:          dict  = field(default_factory=dict)

    # Filled at runtime — do not set manually
    execution_log_id: Optional[str] = field(default=None, init=False, repr=False)

    # Injected by the context manager — callable on the instance
    get_microsoft_token: Optional[Callable[[], str]] = field(
        default=None, init=False, repr=False
    )


# ── Context manager ───────────────────────────────────────────────────────────


@contextmanager
def execution_context(
    ctx: ExecutionContext,
    db_conn: psycopg2.extensions.connection,
):
    """
    Context manager that bookends every system operation with audit logging
    and safe token access.

    On enter:
      - Inserts a 'running' row in task_execution_log.
      - Attaches ctx.get_microsoft_token() — always fetches owner's token.

    On exit (success):
      - Updates the log row to 'completed'.

    On exit (token error):
      - Updates the log row to 'token_expired' or 'no_permission'.
      - Inserts a user_notification so the frontend shows a banner.
      - Re-raises the exception so callers can react.

    On exit (security violation):
      - Updates the log row to 'failed' with a SECURITY prefix in error_detail.
      - Re-raises — never silenced.

    On exit (any other exception):
      - Updates the log row to 'failed'.
      - Re-raises.
    """

    # ── Create execution log row ──────────────────────────────────────────────
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO task_execution_log (
                tenant_id, owner_user_id, triggered_by,
                triggered_by_user_id, task_type, task_detail, status
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'running')
            RETURNING id
            """,
            (
                ctx.tenant_id,
                ctx.owner_user_id,
                ctx.triggered_by,
                ctx.triggered_by_user_id if ctx.triggered_by_user_id != "system" else None,
                ctx.task_type,
                json.dumps(ctx.task_detail or {}),
            ),
        )
        ctx.execution_log_id = str(cur.fetchone()[0])
    db_conn.commit()

    # ── Attach token accessor ─────────────────────────────────────────────────
    def _get_microsoft_token() -> str:
        """
        Fetch the Microsoft access token for the OWNER of this context.
        Uses MicrosoftTokenManager to enforce security invariants.
        Updates task_execution_log.used_microsoft_token on first call.
        """
        manager = MicrosoftTokenManager(db_conn)
        token = manager.get_valid_token(
            user_id=ctx.owner_user_id,
            tenant_id=ctx.tenant_id,
            requesting_user_id=ctx.triggered_by_user_id,
            task_type=ctx.task_type,
        )
        # Record that this execution used Microsoft access
        with db_conn.cursor() as cur:
            cur.execute(
                """
                UPDATE task_execution_log
                SET used_microsoft_token  = TRUE,
                    token_owner_user_id   = %s
                WHERE id = %s
                """,
                (ctx.owner_user_id, ctx.execution_log_id),
            )
        db_conn.commit()
        return token

    ctx.get_microsoft_token = _get_microsoft_token

    # ── Run task body ─────────────────────────────────────────────────────────
    try:
        yield ctx

        # ── Success ───────────────────────────────────────────────────────────
        _update_log(db_conn, ctx.execution_log_id, "completed")

    except (TokenExpiredError, TokenInvalidError) as exc:
        log.error(
            "execution_context: token error | owner=%s task=%s: %s",
            ctx.owner_user_id, ctx.task_type, exc,
        )
        _update_log(db_conn, ctx.execution_log_id, "token_expired", str(exc))
        _notify_token_expired(ctx.owner_user_id, ctx.tenant_id, db_conn)
        raise

    except TokenNotFoundError as exc:
        log.warning(
            "execution_context: token not found | owner=%s task=%s: %s",
            ctx.owner_user_id, ctx.task_type, exc,
        )
        _update_log(db_conn, ctx.execution_log_id, "no_permission", str(exc))
        raise

    except SecurityViolationError as exc:
        # This should never happen — it indicates a code bug.
        log.critical(
            "SECURITY VIOLATION in execution_context | owner=%s "
            "triggered_by=%s task=%s: %s",
            ctx.owner_user_id,
            ctx.triggered_by_user_id,
            ctx.task_type,
            exc,
        )
        _update_log(
            db_conn,
            ctx.execution_log_id,
            "failed",
            f"[SECURITY VIOLATION] {exc}",
        )
        raise

    except Exception as exc:
        log.exception(
            "execution_context: task failed | owner=%s task=%s",
            ctx.owner_user_id, ctx.task_type,
        )
        _update_log(db_conn, ctx.execution_log_id, "failed", str(exc)[:500])
        raise


# ── Internal helpers ──────────────────────────────────────────────────────────


def _update_log(
    db_conn: psycopg2.extensions.connection,
    log_id: str,
    status: str,
    error_detail: Optional[str] = None,
) -> None:
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                UPDATE task_execution_log
                SET status       = %s,
                    error_detail = %s,
                    completed_at = NOW()
                WHERE id = %s
                """,
                (status, error_detail, log_id),
            )
        db_conn.commit()
    except Exception as exc:
        # Never let audit logging failure hide the real error
        log.warning("execution_context: could not update log row %s: %s", log_id, exc)


def _notify_token_expired(
    user_id: str,
    tenant_id: str,
    db_conn: psycopg2.extensions.connection,
) -> None:
    """
    Upsert a 'token_expired' notification for the user.
    The frontend polls /api/proxy/notifications/unread and shows a banner.
    Only the owner (user_id) receives this notification — never the triggerer.
    """
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_notifications
                  (user_id, tenant_id, type, message, action_url, is_read)
                VALUES (%s, %s, 'token_expired',
                  'Tu conexión con Microsoft expiró. Reconecta para continuar.',
                  '/settings/microsoft',
                  FALSE)
                ON CONFLICT (user_id, type) DO UPDATE
                  SET created_at = NOW(),
                      is_read    = FALSE
                """,
                (user_id, tenant_id),
            )
        db_conn.commit()
    except Exception as exc:
        log.warning(
            "execution_context: could not create token_expired notification "
            "for user=%s: %s",
            user_id,
            exc,
        )
