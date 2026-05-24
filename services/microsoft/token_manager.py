"""
services/microsoft/token_manager.py — Centralised Microsoft token access.

ABSOLUTE RULE:
  No part of the system touches microsoft_platform_tokens directly.
  All access goes through this module.
  This is the only place that can prevent a cross-user token leak.

Security model:
  - A user may only access their own token.
  - The cron scheduler may access any token on behalf of the schedule's
    owner_user_id, identified by requesting_user_id='system'.
  - Any other cross-user access raises SecurityViolationError immediately.
  - The tenant_id subquery prevents cross-tenant token access even if
    user UUIDs collide across tenants (they shouldn't, but defence-in-depth).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg2.extensions

log = logging.getLogger(__name__)

# ── Exceptions ────────────────────────────────────────────────────────────────


class TokenNotFoundError(Exception):
    """User has not connected their Microsoft account."""


class TokenExpiredError(Exception):
    """Token expired and could not be refreshed — user must reconnect."""


class TokenInvalidError(Exception):
    """Token permanently invalidated after repeated refresh failures."""


class SecurityViolationError(Exception):
    """Attempt to use another user's token — this is a critical code bug."""


# ── Constants ─────────────────────────────────────────────────────────────────

_REFRESH_AHEAD_MINUTES = 5        # refresh if expiring within this window
_MAX_REFRESH_ERRORS    = 3        # invalidate after this many consecutive failures


# ── Manager ───────────────────────────────────────────────────────────────────


class MicrosoftTokenManager:
    """
    Thread-safe token accessor.  Pass a live psycopg2 connection.
    The connection is NOT closed by this class — caller owns its lifecycle.
    """

    def __init__(self, db_conn: psycopg2.extensions.connection) -> None:
        self._db = db_conn

    # ── Public API ────────────────────────────────────────────────────────────

    def get_valid_token(
        self,
        *,
        user_id: str,
        tenant_id: str,
        requesting_user_id: str,
        task_type: str,
    ) -> str:
        """
        Return a valid (non-expired) decrypted access token for `user_id`.

        Args:
            user_id:             Owner of the token to retrieve.
            tenant_id:           Tenant that owns `user_id` (isolation check).
            requesting_user_id:  Who is asking. Must equal `user_id` or 'system'.
            task_type:           Used in audit/log entries only.

        Returns:
            Decrypted Microsoft access token string.

        Raises:
            SecurityViolationError: requesting_user_id ≠ user_id and ≠ 'system'.
            TokenNotFoundError:     No token row found for user+tenant pair.
            TokenInvalidError:      Token permanently marked is_valid=FALSE.
            TokenExpiredError:      Refresh failed; user must reconnect.
        """
        self._check_authorization(user_id, requesting_user_id, task_type)

        row = self._load_token_row(user_id, tenant_id)

        if not row["is_valid"]:
            raise TokenInvalidError(
                f"Token for user {user_id} is permanently invalid "
                f"(refresh_error_count={row['refresh_error_count']}). "
                "User must reconnect from /settings/microsoft."
            )

        now = datetime.now(timezone.utc)
        expires_at = row["token_expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        needs_refresh = (expires_at - now) < timedelta(minutes=_REFRESH_AHEAD_MINUTES)

        if needs_refresh:
            log.info("token_manager: token for user=%s expiring soon — refreshing", user_id)
            access_token = self._refresh_token(
                user_id=user_id,
                token_record_id=row["id"],
                encrypted_refresh_token=row["encrypted_refresh_token"],
                refresh_error_count=row["refresh_error_count"],
            )
        else:
            from services.microsoft.crypto import decrypt  # noqa: PLC0415
            access_token = decrypt(row["encrypted_access_token"])

        self._record_usage(user_id)
        return access_token

    def invalidate_token(self, *, user_id: str, tenant_id: str) -> None:
        """Mark a token permanently invalid. User must reconnect."""
        with self._db.cursor() as cur:
            cur.execute(
                """
                UPDATE microsoft_platform_tokens
                SET is_valid = FALSE
                WHERE user_id = %s
                  AND EXISTS (
                    SELECT 1 FROM users
                    WHERE id = %s AND tenant_id = %s
                  )
                """,
                (user_id, user_id, tenant_id),
            )
        self._db.commit()
        log.warning("token_manager: token for user=%s manually invalidated", user_id)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _check_authorization(
        self,
        user_id: str,
        requesting_user_id: str,
        task_type: str,
    ) -> None:
        """
        Enforce the ownership invariant.

        A user may only access their own token.
        The scheduler may act as 'system' on behalf of a configured owner.
        Anything else is a critical bug.
        """
        if requesting_user_id == user_id:
            return
        if requesting_user_id == "system":
            return

        # Anything else: log as CRITICAL (not error) and refuse immediately.
        log.critical(
            "SECURITY VIOLATION: user %s attempted to access token of user %s "
            "(task_type=%s). This is a code bug — investigate immediately.",
            requesting_user_id,
            user_id,
            task_type,
        )
        raise SecurityViolationError(
            f"User {requesting_user_id} cannot use the token of {user_id}. "
            "Each user may only access their own Microsoft token."
        )

    def _load_token_row(self, user_id: str, tenant_id: str) -> dict:
        """
        Load the token record, verifying tenant ownership via subquery.
        Returns a dict with all relevant columns.
        Raises TokenNotFoundError if no matching row exists.
        """
        with self._db.cursor() as cur:
            cur.execute(
                """
                SELECT
                    t.id,
                    t.encrypted_access_token,
                    t.encrypted_refresh_token,
                    t.token_expires_at,
                    t.scopes_granted,
                    t.is_valid,
                    t.refresh_error_count
                FROM microsoft_platform_tokens t
                WHERE t.user_id = %s
                  AND EXISTS (
                    SELECT 1 FROM users u
                    WHERE u.id = %s
                      AND u.tenant_id = %s
                  )
                """,
                (user_id, user_id, tenant_id),
            )
            row = cur.fetchone()

        if row is None:
            raise TokenNotFoundError(
                f"No Microsoft token found for user {user_id} in tenant {tenant_id}. "
                "User must connect their Microsoft account from /settings/microsoft."
            )

        return {
            "id":                     str(row[0]),
            "encrypted_access_token": row[1],
            "encrypted_refresh_token": row[2],
            "token_expires_at":       row[3],
            "scopes_granted":         row[4],
            "is_valid":               row[5],
            "refresh_error_count":    row[6],
        }

    def _refresh_token(
        self,
        *,
        user_id: str,
        token_record_id: str,
        encrypted_refresh_token: str,
        refresh_error_count: int,
    ) -> str:
        """
        Call Microsoft's token endpoint to get a new access token.

        On success: stores updated tokens, resets error counters.
        On failure: increments error counter; invalidates after _MAX_REFRESH_ERRORS.
        Raises TokenExpiredError so the caller can notify the user.
        """
        import httpx  # noqa: PLC0415
        from services.microsoft.crypto import decrypt, encrypt  # noqa: PLC0415

        refresh_token = decrypt(encrypted_refresh_token)

        tenant_id_ms = os.environ.get("MICROSOFT_PLATFORM_TENANT_ID", "common")
        client_id    = os.environ["MICROSOFT_PLATFORM_CLIENT_ID"]
        client_secret = os.environ["MICROSOFT_PLATFORM_CLIENT_SECRET"]
        scopes       = os.environ.get(
            "MICROSOFT_PLATFORM_SCOPES",
            "offline_access Files.Read.All Mail.Read",
        )

        try:
            resp = httpx.post(
                f"https://login.microsoftonline.com/{tenant_id_ms}/oauth2/v2.0/token",
                data={
                    "client_id":     client_id,
                    "client_secret": client_secret,
                    "grant_type":    "refresh_token",
                    "refresh_token": refresh_token,
                    "scope":         scopes,
                },
                timeout=15.0,
            )

            if resp.status_code != 200:
                raise RuntimeError(
                    f"Microsoft token endpoint returned HTTP {resp.status_code}: "
                    f"{resp.text[:300]}"
                )

            data = resp.json()
            new_access  = data["access_token"]
            new_refresh = data.get("refresh_token", refresh_token)
            expires_in  = int(data.get("expires_in", 3600))

            with self._db.cursor() as cur:
                cur.execute(
                    """
                    UPDATE microsoft_platform_tokens
                    SET encrypted_access_token  = %s,
                        encrypted_refresh_token = %s,
                        token_expires_at        = NOW() + (%s * INTERVAL '1 second'),
                        last_refreshed_at       = NOW(),
                        refresh_error_count     = 0,
                        last_refresh_error      = NULL
                    WHERE id = %s
                    """,
                    (
                        encrypt(new_access),
                        encrypt(new_refresh),
                        expires_in - 300,   # 5-minute safety margin
                        token_record_id,
                    ),
                )
            self._db.commit()
            log.info("token_manager: token for user=%s refreshed successfully", user_id)
            return new_access

        except Exception as exc:
            log.error(
                "token_manager: refresh failed for user=%s (attempt %d/%d): %s",
                user_id,
                refresh_error_count + 1,
                _MAX_REFRESH_ERRORS,
                exc,
            )

            new_count = refresh_error_count + 1
            will_invalidate = new_count >= _MAX_REFRESH_ERRORS

            with self._db.cursor() as cur:
                cur.execute(
                    """
                    UPDATE microsoft_platform_tokens
                    SET refresh_error_count = %s,
                        last_refresh_error  = %s,
                        is_valid            = CASE WHEN %s THEN FALSE ELSE is_valid END
                    WHERE id = %s
                    """,
                    (
                        new_count,
                        str(exc)[:500],
                        will_invalidate,
                        token_record_id,
                    ),
                )
            self._db.commit()

            if will_invalidate:
                log.warning(
                    "token_manager: token for user=%s invalidated after %d failures",
                    user_id,
                    _MAX_REFRESH_ERRORS,
                )

            raise TokenExpiredError(
                f"Could not refresh Microsoft token for user {user_id}. "
                "User must reconnect from /settings/microsoft. "
                f"Underlying error: {exc}"
            ) from exc

    def _record_usage(self, user_id: str) -> None:
        """Update last_used_at and use_count. Non-fatal — log on error."""
        try:
            with self._db.cursor() as cur:
                cur.execute(
                    """
                    UPDATE microsoft_platform_tokens
                    SET last_used_at = NOW(),
                        use_count    = use_count + 1
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )
            self._db.commit()
        except Exception as exc:
            log.warning(
                "token_manager: could not update usage stats for user=%s: %s",
                user_id,
                exc,
            )
