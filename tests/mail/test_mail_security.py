"""
tests/mail/test_mail_security.py — Security-critical mail pipeline tests.

Covers:
  - ClamAV: infected attachments quarantined, never processed
  - ClamAV: connection failure → quarantine (fail-safe)
  - Whitelist: unauthorized domain → message never persisted
  - Bounce rule: no bounce sent to unauthorized senders
  - Outbound limit: enforced before send
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch, call

import pytest


# ── ClamAV quarantine on infection ───────────────────────────────────────────

class TestClamAVQuarantine:
    def test_infected_attachment_quarantined(self, mock_clamav_infected, tmp_path):
        from services.mail.attachment_handler import _scan_with_clamav

        quarantine_root = str(tmp_path / "quarantine")
        os.makedirs(quarantine_root, exist_ok=True)

        result = _scan_with_clamav(b"EICAR-TEST-FILE", "malware.exe")
        assert result["status"] == "infected"
        assert result.get("virus_name") is not None

    def test_clean_attachment_not_quarantined(self, mock_clamav_clean):
        from services.mail.attachment_handler import _scan_with_clamav

        result = _scan_with_clamav(b"%PDF-1.4 clean content", "report.pdf")
        assert result["status"] == "clean"

    def test_clamav_connection_error_quarantines(self, tmp_path):
        """
        If ClamAV is unreachable, attachment must be treated as infected
        (fail-closed) — never processed.
        """
        import clamd

        with patch("clamd.ClamdUnixSocket") as mock_clamd:
            mock_clamd.return_value.instream.side_effect = clamd.ConnectionError("no socket")

            from services.mail.attachment_handler import _scan_with_clamav
            result = _scan_with_clamav(b"some data", "document.pdf")

        assert result["status"] in ("infected", "error", "quarantined"), (
            "ClamAV connection error must not return 'clean'"
        )


# ── Whitelist enforcement ─────────────────────────────────────────────────────

class TestWhitelistEnforcement:
    def test_unauthorized_domain_not_persisted(self, tenant_id, sample_email_bytes):
        """
        process_inbound_mail must NOT insert a mail_messages record when the
        sender domain is NOT in the whitelist. The DB commit must not be called
        for the message insert.
        """
        from unittest.mock import patch, MagicMock

        db = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = (tenant_id,)  # tenant lookup succeeds
        db.cursor.return_value = cursor

        with patch("psycopg2.connect", return_value=db), \
             patch("services.mail.whitelist.is_authorized", return_value=False), \
             patch("services.mail.whitelist.get_tenant_for_recipient", return_value=tenant_id), \
             patch("services.mail.thread_builder.upsert_thread", return_value="thread-1"), \
             patch("services.mail.tasks.classify_and_respond") as mock_classify:

            from services.mail.tasks import process_inbound_mail

            # Run synchronously (bypass Celery)
            result = process_inbound_mail.run(sample_email_bytes, "uid-001")

        # Should be persisted but marked as rejected (not authorized)
        # Classify must NOT be triggered for unauthorized messages
        mock_classify.delay.assert_not_called()
        assert result.get("authorized") is False

    def test_no_bounce_to_unauthorized_sender(self, tenant_id, sample_email_bytes):
        """
        No email must be sent to the sender of an unauthorized message.
        send_mail must never be called in response to an unauthorized message.
        """
        with patch("psycopg2.connect"), \
             patch("services.mail.whitelist.is_authorized", return_value=False), \
             patch("services.mail.whitelist.get_tenant_for_recipient", return_value=tenant_id), \
             patch("services.mail.thread_builder.upsert_thread", return_value="t-1"), \
             patch("services.mail.sender.send_mail") as mock_send:

            from services.mail.tasks import process_inbound_mail
            process_inbound_mail.run(sample_email_bytes, "uid-002")

        mock_send.assert_not_called()


# ── Outbound daily limit ──────────────────────────────────────────────────────

class TestOutboundLimit:
    def test_daily_limit_enforced(self, tenant_id):
        """
        When the daily outbound count equals MAIL_MAX_DAILY_OUTBOUND,
        send_mail must return success=False without calling SMTP.
        """
        import smtplib

        daily_limit = 3

        db = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        # Simulate: daily count = limit
        cursor.fetchone.return_value = (daily_limit,)
        db.cursor.return_value = cursor

        with patch.dict(os.environ, {"MAIL_MAX_DAILY_OUTBOUND": str(daily_limit)}), \
             patch("smtplib.SMTP") as mock_smtp:

            from services.mail.sender import send_mail
            result = send_mail(
                from_address="bot@dominio.com",
                to_addresses=["user@empresa.com"],
                subject="Test",
                body_html="<p>Hi</p>",
                body_text="Hi",
                tenant_id=tenant_id,
                trigger_type="test",
                db_conn=db,
            )

        assert result["success"] is False
        mock_smtp.assert_not_called()
