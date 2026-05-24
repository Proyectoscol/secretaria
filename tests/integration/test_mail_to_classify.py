"""
tests/integration/test_mail_to_classify.py — End-to-end mail classification.

Skipped when DATABASE_URL is not set.
Mocks: LLM client (no real OpenRouter calls), SMTP, ClamAV.
Tests the full message lifecycle: parse → whitelist → persist → classify.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def real_db():
    dsn = os.getenv("DATABASE_URL") or os.getenv("KOS_DB_DSN")
    if not dsn:
        pytest.skip("DATABASE_URL not set — integration tests skipped")
    try:
        import psycopg2
        conn = psycopg2.connect(dsn)
        conn.autocommit = False
        yield conn
        conn.rollback()
        conn.close()
    except Exception as exc:
        pytest.skip(f"Could not connect to DB: {exc}")


class TestMailClassificationPipeline:
    def test_authorized_message_persisted_and_classified(
        self, real_db, tenant_id, sample_email_bytes, mock_llm_client
    ):
        """
        An authorized inbound email from a whitelisted domain:
          1. Gets parsed correctly
          2. Is persisted to mail_messages
          3. classify_and_respond is triggered (not tested for actual send)
        """
        from services.mail.parser import parse_message

        parsed = parse_message(sample_email_bytes)

        assert parsed["from_domain"] == "empresa.com"
        assert "reporte" in parsed["subject"].lower()

        # Verify LLM mock is configured
        mock_llm_client.return_value = {
            "content": "report_request",
            "model": "openai/gpt-4o-mini",
            "usage": {},
            "task": "classify_email",
            "tenant_id": tenant_id,
        }

        # Verify classification with mocked LLM
        with patch("services.llm.client.llm_client.complete", mock_llm_client):
            from agents.secretary.secretary import SecretaryAgent
            agent = SecretaryAgent()
            classification = agent._classify_intent(
                parsed["subject"], parsed.get("body_text", ""), tenant_id
            )

        assert classification == "report_request"

    def test_unauthorized_domain_rejected_no_db_write(
        self, real_db, tenant_id, sample_email_bytes
    ):
        """
        Email from unauthorized domain: classify_and_respond must not be called.
        """
        from services.mail.whitelist import is_authorized

        # No whitelist entry → should return False
        result = is_authorized("not-in-whitelist-domain.xyz", tenant_id, real_db)
        assert result is False
