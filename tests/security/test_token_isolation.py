"""
tests/security/test_token_isolation.py — Token isolation security tests.

These tests MUST NEVER fail.  A failure means there is a security bug
in the token access layer.  run_tests.sh runs these in Stage 0, before
any other test, and aborts the entire suite on failure.

Coverage:
  1. Cross-user token access blocked
  2. Own-token access allowed
  3. System cron access allowed for scheduled tasks
  4. Cross-tenant access blocked via subquery
  5. SecurityViolationError logged at CRITICAL level
  6. Expired-token notification targets the owner, not the triggerer
  7. ExecutionContext always logs owner_user_id
"""

from __future__ import annotations

import logging
import os
from unittest.mock import MagicMock, call, patch

import pytest


# ── Shared fixtures ───────────────────────────────────────────────────────────

CAMILO = "00000000-0000-0000-0000-000000000001"
CESAR  = "00000000-0000-0000-0000-000000000002"
TENANT = "00000000-0000-0000-0000-000000000099"

# A minimal valid token row returned by the mocked DB cursor
_VALID_TOKEN_ROW = (
    "row-id-uuid",                    # id
    "encrypted_access_token_here",    # encrypted_access_token
    "encrypted_refresh_token_here",   # encrypted_refresh_token
    None,                             # token_expires_at (overridden per test)
    ["offline_access", "Mail.Read"],  # scopes_granted
    True,                             # is_valid
    0,                                # refresh_error_count
)


@pytest.fixture(autouse=True)
def fake_encryption_key(monkeypatch):
    """Provide a valid 32-byte key so crypto operations don't raise."""
    import base64
    key = base64.b64encode(b"\x00" * 32).decode()
    monkeypatch.setenv("MICROSOFT_TOKEN_ENCRYPTION_KEY", key)


def _make_db_with_token(expires_delta_minutes: int = 60) -> MagicMock:
    """
    Return a mock psycopg2 connection that returns a valid token row
    with `expires_delta_minutes` minutes until expiry.
    """
    from datetime import datetime, timedelta, timezone

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_delta_minutes)
    row = _VALID_TOKEN_ROW[:3] + (expires_at,) + _VALID_TOKEN_ROW[4:]

    db = MagicMock()
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.fetchone.return_value = row
    db.cursor.return_value = cursor
    return db


# ── 1. Cross-user access blocked ─────────────────────────────────────────────

class TestCrossUserAccessBlocked:

    def test_cesar_cannot_use_camilos_token(self):
        """
        César (different user) requesting Camilo's token must raise
        SecurityViolationError immediately — no DB query for the token.
        """
        from services.microsoft.token_manager import (
            MicrosoftTokenManager, SecurityViolationError,
        )

        db = MagicMock()
        manager = MicrosoftTokenManager(db)

        with pytest.raises(SecurityViolationError) as exc_info:
            manager.get_valid_token(
                user_id=CAMILO,
                tenant_id=TENANT,
                requesting_user_id=CESAR,      # ← different user: forbidden
                task_type="read_mail",
            )

        assert CESAR  in str(exc_info.value)
        assert CAMILO in str(exc_info.value)

    def test_cross_user_does_not_query_db(self):
        """The DB must never be queried when a security violation is detected."""
        from services.microsoft.token_manager import (
            MicrosoftTokenManager, SecurityViolationError,
        )

        db = MagicMock()
        manager = MicrosoftTokenManager(db)

        with pytest.raises(SecurityViolationError):
            manager.get_valid_token(
                user_id=CAMILO,
                tenant_id=TENANT,
                requesting_user_id=CESAR,
                task_type="read_mail",
            )

        # No DB interaction should have occurred
        db.cursor.assert_not_called()

    def test_empty_requesting_user_blocked(self):
        """Empty string as requesting_user_id must also be rejected."""
        from services.microsoft.token_manager import (
            MicrosoftTokenManager, SecurityViolationError,
        )
        db = MagicMock()
        manager = MicrosoftTokenManager(db)

        with pytest.raises(SecurityViolationError):
            manager.get_valid_token(
                user_id=CAMILO,
                tenant_id=TENANT,
                requesting_user_id="",          # ← empty: forbidden
                task_type="read_mail",
            )


# ── 2. Own-token access allowed ───────────────────────────────────────────────

class TestOwnTokenAccess:

    def test_camilo_can_access_own_token(self):
        """
        Camilo requesting his own token must succeed (no exception).
        decrypt() is mocked so we don't need a real encrypted value.
        """
        from services.microsoft.token_manager import MicrosoftTokenManager

        db = _make_db_with_token(expires_delta_minutes=60)

        with patch("services.microsoft.crypto.decrypt", return_value="access-token-abc"):
            manager = MicrosoftTokenManager(db)
            token = manager.get_valid_token(
                user_id=CAMILO,
                tenant_id=TENANT,
                requesting_user_id=CAMILO,      # ← same user: allowed
                task_type="read_mail",
            )

        assert token == "access-token-abc"

    def test_returned_token_is_decrypted(self):
        """The token returned must be the decrypted plaintext, not the DB bytes."""
        from services.microsoft.token_manager import MicrosoftTokenManager

        db = _make_db_with_token(expires_delta_minutes=60)
        plain = "plain-access-token-xyz"

        with patch("services.microsoft.crypto.decrypt", return_value=plain):
            manager = MicrosoftTokenManager(db)
            token = manager.get_valid_token(
                user_id=CAMILO,
                tenant_id=TENANT,
                requesting_user_id=CAMILO,
                task_type="read_mail",
            )

        assert token == plain


# ── 3. System / cron access allowed ──────────────────────────────────────────

class TestSystemCronAccess:

    def test_system_can_access_owner_token_for_cron(self):
        """
        requesting_user_id='system' is the only non-owner value allowed.
        This is how Celery Beat accesses the schedule owner's token.
        """
        from services.microsoft.token_manager import MicrosoftTokenManager

        db = _make_db_with_token(expires_delta_minutes=60)

        with patch("services.microsoft.crypto.decrypt", return_value="cron-token"):
            manager = MicrosoftTokenManager(db)
            token = manager.get_valid_token(
                user_id=CAMILO,
                tenant_id=TENANT,
                requesting_user_id="system",    # ← cron: allowed
                task_type="send_report",
            )

        assert token == "cron-token"

    def test_arbitrary_string_not_treated_as_system(self):
        """'SYSTEM' (capitalised) or 'sys' must NOT bypass the check."""
        from services.microsoft.token_manager import (
            MicrosoftTokenManager, SecurityViolationError,
        )
        db = MagicMock()
        manager = MicrosoftTokenManager(db)

        for bad_value in ("SYSTEM", "sys", "scheduler", " system"):
            with pytest.raises(SecurityViolationError, match=""):
                manager.get_valid_token(
                    user_id=CAMILO,
                    tenant_id=TENANT,
                    requesting_user_id=bad_value,
                    task_type="send_report",
                )


# ── 4. Cross-tenant access blocked ───────────────────────────────────────────

class TestCrossTenantBlocked:

    def test_token_not_found_for_wrong_tenant(self):
        """
        The DB query uses a subquery to verify tenant_id.
        If user_id exists but in a different tenant, fetchone returns None
        and TokenNotFoundError is raised.
        """
        from services.microsoft.token_manager import (
            MicrosoftTokenManager, TokenNotFoundError,
        )

        db = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = None   # subquery failed to match tenant
        db.cursor.return_value = cursor

        manager = MicrosoftTokenManager(db)

        with pytest.raises(TokenNotFoundError):
            manager.get_valid_token(
                user_id=CAMILO,
                tenant_id="wrong-tenant-uuid",
                requesting_user_id=CAMILO,
                task_type="read_mail",
            )

    def test_db_query_includes_tenant_id(self):
        """The SQL query must include tenant_id in WHERE — verified via call args."""
        from services.microsoft.token_manager import (
            MicrosoftTokenManager, TokenNotFoundError,
        )

        executed_params: list = []

        db = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = None

        def capture_execute(query, params):
            executed_params.append(params)

        cursor.execute = capture_execute
        db.cursor.return_value = cursor

        manager = MicrosoftTokenManager(db)
        try:
            manager.get_valid_token(
                user_id=CAMILO,
                tenant_id=TENANT,
                requesting_user_id=CAMILO,
                task_type="test",
            )
        except Exception:
            pass

        # tenant_id must appear in the query parameters
        all_params = " ".join(str(p) for p in executed_params)
        assert TENANT in all_params, (
            "tenant_id must be passed to the DB query for cross-tenant isolation"
        )


# ── 5. SecurityViolationError logged at CRITICAL ──────────────────────────────

class TestSecurityViolationLogging:

    def test_cross_user_logged_as_critical(self, caplog):
        """A cross-user attempt must produce at least one CRITICAL log record."""
        from services.microsoft.token_manager import (
            MicrosoftTokenManager, SecurityViolationError,
        )

        db = MagicMock()
        manager = MicrosoftTokenManager(db)

        with caplog.at_level(logging.CRITICAL, logger="services.microsoft.token_manager"):
            with pytest.raises(SecurityViolationError):
                manager.get_valid_token(
                    user_id=CAMILO,
                    tenant_id=TENANT,
                    requesting_user_id=CESAR,
                    task_type="read_mail",
                )

        critical_records = [r for r in caplog.records if r.levelno == logging.CRITICAL]
        assert len(critical_records) >= 1, (
            "A SecurityViolationError must produce at least one CRITICAL log record"
        )
        assert "SECURITY VIOLATION" in critical_records[0].message

    def test_critical_message_includes_both_user_ids(self, caplog):
        from services.microsoft.token_manager import (
            MicrosoftTokenManager, SecurityViolationError,
        )

        db = MagicMock()
        manager = MicrosoftTokenManager(db)

        with caplog.at_level(logging.CRITICAL):
            with pytest.raises(SecurityViolationError):
                manager.get_valid_token(
                    user_id=CAMILO,
                    tenant_id=TENANT,
                    requesting_user_id=CESAR,
                    task_type="read_mail",
                )

        critical_msgs = [r.message for r in caplog.records if r.levelno == logging.CRITICAL]
        combined = " ".join(critical_msgs)
        assert CAMILO in combined, "Critical log must include the token owner's user_id"
        assert CESAR  in combined, "Critical log must include the requesting user_id"


# ── 6. Token expiry notification targets the owner ───────────────────────────

class TestTokenExpiryNotification:

    def test_notification_sent_to_owner_not_triggerer(self):
        """
        When Camilo's token expires during a cron job (triggered by 'system'),
        the notification must be inserted for CAMILO (owner), not for 'system'.
        """
        from services.execution_context import _notify_token_expired

        db = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        db.cursor.return_value = cursor

        # The cron fires the task with triggered_by='system'
        # but the owner is CAMILO
        _notify_token_expired(
            user_id=CAMILO,    # owner
            tenant_id=TENANT,
            db_conn=db,
        )

        # Verify the INSERT used CAMILO's user_id
        all_calls = cursor.execute.call_args_list
        assert len(all_calls) >= 1
        call_params = all_calls[0][0][1]   # positional args to execute()
        assert CAMILO in str(call_params), (
            "Token expiry notification must target the owner (CAMILO), not 'system'"
        )
        assert "system" not in str(call_params), (
            "Notification must not target 'system' — that is not a real user"
        )

    def test_execution_context_notifies_owner_on_token_expiry(self):
        """
        ExecutionContext must call _notify_token_expired with owner_user_id
        when a TokenExpiredError bubbles up from get_microsoft_token().
        """
        from services.execution_context import ExecutionContext, execution_context
        from services.microsoft.token_manager import TokenExpiredError

        # DB mock — needs to create the execution log row and update it
        db = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = ("log-row-uuid",)
        db.cursor.return_value = cursor

        ctx = ExecutionContext(
            tenant_id=TENANT,
            owner_user_id=CAMILO,
            triggered_by="scheduled",
            triggered_by_user_id="system",
            task_type="send_report",
        )

        notified_users: list = []

        def fake_notify(user_id, tenant_id, db_conn):
            notified_users.append(user_id)

        with patch("services.execution_context._notify_token_expired", fake_notify):
            with pytest.raises(TokenExpiredError):
                with execution_context(ctx, db) as exec_ctx:
                    raise TokenExpiredError("test expiry")

        assert CAMILO in notified_users, "Owner (Camilo) must receive the notification"
        assert "system" not in notified_users, "'system' is not a user — must not be notified"


# ── 7. ExecutionContext always logs owner_user_id ────────────────────────────

class TestExecutionContextAudit:

    def test_execution_log_row_created_with_owner(self):
        """
        Every execution_context must INSERT a task_execution_log row
        that includes owner_user_id.
        """
        from services.execution_context import ExecutionContext, execution_context

        db = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = ("log-uuid",)
        db.cursor.return_value = cursor

        inserted_params: list = []

        def capture(query, params):
            if "INSERT INTO task_execution_log" in query:
                inserted_params.append(params)
            cursor.fetchone.return_value = ("log-uuid",)

        cursor.execute = capture

        ctx = ExecutionContext(
            tenant_id=TENANT,
            owner_user_id=CAMILO,
            triggered_by="manual",
            triggered_by_user_id=CAMILO,
            task_type="test_task",
        )

        with execution_context(ctx, db):
            pass   # do nothing — just verify the INSERT happened

        assert len(inserted_params) >= 1, "task_execution_log INSERT must have fired"
        insert_str = str(inserted_params[0])
        assert CAMILO in insert_str, "owner_user_id must be in the INSERT params"
        assert TENANT in insert_str, "tenant_id must be in the INSERT params"
