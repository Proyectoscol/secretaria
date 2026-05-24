"""
tests/mail/test_whitelist.py — Unit tests for services/mail/whitelist.py.

Verifies:
  - Authorized domain returns True
  - Unauthorized domain returns False
  - Empty whitelist rejects everything
  - Subdomain is NOT authorized by parent domain (no wildcards)
  - DB error returns False (fail-safe, never raises)
  - get_tenant_for_recipient returns correct tenant_id
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestIsAuthorized:
    def _make_db(self, rows: list) -> MagicMock:
        db = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = rows[0] if rows else None
        db.cursor.return_value = cursor
        return db

    def test_authorized_domain_returns_true(self, tenant_id):
        from services.mail.whitelist import is_authorized

        db = self._make_db([(True,)])
        result = is_authorized("empresa.com", tenant_id, db)
        assert result is True

    def test_unauthorized_domain_returns_false(self, tenant_id):
        from services.mail.whitelist import is_authorized

        db = self._make_db([None])  # fetchone returns None → domain not found
        result = is_authorized("spam.com", tenant_id, db)
        assert result is False

    def test_empty_whitelist_rejects_all(self, tenant_id):
        from services.mail.whitelist import is_authorized

        db = self._make_db([None])
        result = is_authorized("empresa.com", tenant_id, db)
        assert result is False

    def test_subdomain_not_authorized_by_parent(self, tenant_id):
        """
        'sub.empresa.com' must NOT be authorized just because 'empresa.com'
        is in the whitelist. No wildcard matching.
        """
        from services.mail.whitelist import is_authorized

        db = self._make_db([None])
        result = is_authorized("sub.empresa.com", tenant_id, db)
        assert result is False

    def test_db_error_returns_false_failsafe(self, tenant_id):
        from services.mail.whitelist import is_authorized

        db = MagicMock()
        db.cursor.side_effect = Exception("DB connection lost")
        # Must not raise — fail-safe returns False
        result = is_authorized("empresa.com", tenant_id, db)
        assert result is False

    def test_tenant_isolation(self):
        """
        A domain authorized for tenant_A must NOT be authorized for tenant_B.
        The query must include tenant_id in WHERE clause.
        """
        from services.mail.whitelist import is_authorized

        call_args_list: list = []

        db = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = None

        def capture_execute(query, params):
            call_args_list.append(params)

        cursor.execute = capture_execute
        db.cursor.return_value = cursor

        is_authorized("empresa.com", "tenant-A", db)

        # Verify tenant_id was used in the query
        assert any("tenant-A" in str(args) for args in call_args_list), (
            "tenant_id must be in the whitelist query params"
        )


class TestGetTenantForRecipient:
    def test_known_recipient_returns_tenant_id(self, tenant_id):
        from services.mail.whitelist import get_tenant_for_recipient

        db = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = (tenant_id,)
        db.cursor.return_value = cursor

        result = get_tenant_for_recipient("secretaria@midominio.com", db)
        assert result == tenant_id

    def test_unknown_recipient_returns_none(self):
        from services.mail.whitelist import get_tenant_for_recipient

        db = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = None
        db.cursor.return_value = cursor

        result = get_tenant_for_recipient("unknown@other.com", db)
        assert result is None

    def test_db_error_returns_none(self):
        from services.mail.whitelist import get_tenant_for_recipient

        db = MagicMock()
        db.cursor.side_effect = Exception("timeout")
        result = get_tenant_for_recipient("x@y.com", db)
        assert result is None
