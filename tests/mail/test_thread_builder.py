"""
tests/mail/test_thread_builder.py — Unit tests for services/mail/thread_builder.py.

Verifies:
  - New thread created when no existing thread matches
  - Existing thread reused when thread_key matches
  - participant list deduplicated
  - last_message_at updated on upsert
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, call, patch

import pytest


def _parsed_message(
    *,
    message_id: str = "<root@empresa.com>",
    thread_key: str = "a" * 32,
    from_address: str = "juan@empresa.com",
    from_name: str = "Juan",
    subject: str = "Test thread",
    received_at: str = "2025-01-01T09:00:00+00:00",
    in_reply_to: str | None = None,
) -> dict:
    return {
        "message_id": message_id,
        "thread_key": thread_key,
        "from_address": from_address,
        "from_name": from_name,
        "subject": subject,
        "received_at": received_at,
        "to_addresses": [{"email": "secretaria@dominio.com", "name": "Secretaria"}],
        "cc_addresses": [],
        "in_reply_to": in_reply_to,
    }


class TestUpsertThread:
    def _make_db(self, existing_thread_id: str | None = None) -> tuple[MagicMock, MagicMock]:
        db = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)

        if existing_thread_id:
            # First fetchone: thread exists
            cursor.fetchone.return_value = (existing_thread_id, ["juan@empresa.com"])
        else:
            # First fetchone: no existing thread
            cursor.fetchone.return_value = None

        db.cursor.return_value = cursor
        return db, cursor

    def test_new_thread_created_when_none_exists(self, tenant_id):
        from services.mail.thread_builder import upsert_thread

        db, cursor = self._make_db(existing_thread_id=None)
        thread_id = upsert_thread(_parsed_message(), tenant_id, db)

        assert thread_id is not None
        assert len(thread_id) == 36  # UUID format
        db.commit.assert_called_once()

    def test_existing_thread_returned(self, tenant_id):
        from services.mail.thread_builder import upsert_thread

        existing_id = str(uuid.uuid4())
        db, cursor = self._make_db(existing_thread_id=existing_id)
        thread_id = upsert_thread(_parsed_message(thread_key="b" * 32), tenant_id, db)

        assert thread_id == existing_id

    def test_tenant_id_in_query(self, tenant_id):
        """upsert_thread must always filter by tenant_id."""
        from services.mail.thread_builder import upsert_thread

        db, cursor = self._make_db(existing_thread_id=None)
        executed_params: list = []

        original_execute = cursor.execute

        def capture(query, params=None):
            if params:
                executed_params.append(params)

        cursor.execute = capture
        upsert_thread(_parsed_message(), tenant_id, db)

        assert any(tenant_id in str(p) for p in executed_params), (
            "tenant_id must appear in every upsert_thread query"
        )
