"""
tests/conftest.py — Shared pytest fixtures for all KOS test suites.

Fixtures:
  tenant_id            — deterministic test UUID
  mock_db              — MagicMock that looks like a psycopg2 connection
  mock_llm_client      — patches services.llm.client.llm_client.complete
  mock_clamav_clean    — patches clamd.ClamdUnixSocket.instream to return clean
  mock_clamav_infected — patches clamd.ClamdUnixSocket.instream to return infected
  sample_pdf_bytes     — minimal valid 1-page PDF
  sample_email_bytes   — RFC 5322 email with text/plain body
"""

from __future__ import annotations

import email.utils
import io
import os
import textwrap
import uuid
from contextlib import contextmanager
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest


# ── Deterministic test tenant ─────────────────────────────────────────────────

TENANT_UUID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def tenant_id() -> str:
    return TENANT_UUID


# ── Mock DB ───────────────────────────────────────────────────────────────────

class _MockCursor:
    """Minimal cursor that tracks execute calls and returns configurable rows."""

    def __init__(self):
        self.calls: list[tuple] = []
        self._rows: list = []
        self._rowcount: int = 1

    def execute(self, query: str, params=None):
        self.calls.append((query, params))

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    @property
    def rowcount(self):
        return self._rowcount

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


@pytest.fixture
def mock_db():
    """
    MagicMock psycopg2 connection.

    Usage::

        def test_something(mock_db):
            mock_db.cursor.return_value._rows = [(42,)]
            # run code that calls db_conn.cursor() ...
    """
    conn = MagicMock()
    cursor = _MockCursor()
    conn.cursor.return_value = cursor
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.commit = MagicMock()
    conn.rollback = MagicMock()
    conn.close = MagicMock()
    return conn


# ── Mock LLM client ───────────────────────────────────────────────────────────

@pytest.fixture
def mock_llm_client():
    """
    Patches llm_client.complete so no real calls are made to OpenRouter.

    The mock returns a configurable response dict.

    Usage::

        def test_classify(mock_llm_client):
            mock_llm_client.return_value = {
                "content": "report_request",
                "model": "openai/gpt-4o-mini",
                "usage": {},
            }
    """
    with patch(
        "services.llm.client.llm_client.complete",
        return_value={
            "content": "informational",
            "model": "openai/gpt-4o-mini",
            "usage": {"prompt_tokens": 10, "completion_tokens": 1},
            "task": "classify_email",
            "tenant_id": TENANT_UUID,
        },
    ) as mock:
        yield mock


# ── Mock ClamAV ───────────────────────────────────────────────────────────────

@pytest.fixture
def mock_clamav_clean():
    """ClamAV instream returns clean result."""
    with patch("clamd.ClamdUnixSocket") as mock_clamd_class:
        instance = mock_clamd_class.return_value
        instance.instream.return_value = {"stream": ("OK", None)}
        yield instance


@pytest.fixture
def mock_clamav_infected():
    """ClamAV instream returns infected result."""
    with patch("clamd.ClamdUnixSocket") as mock_clamd_class:
        instance = mock_clamd_class.return_value
        instance.instream.return_value = {
            "stream": ("FOUND", "Win.Malware.Agent-12345")
        }
        yield instance


# ── Sample bytes ──────────────────────────────────────────────────────────────

@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """
    Minimal valid 1-page PDF that won't raise on open.
    Contains no meaningful content — just enough structure for magic-number checks.
    """
    # Minimal valid PDF (no external fonts, no images)
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n190\n%%EOF\n"
    )


@pytest.fixture
def sample_email_bytes() -> bytes:
    """
    RFC 5322 plain-text email from an authorized domain.
    Subject contains a report keyword to test classification.
    """
    now = email.utils.formatdate(localtime=False)
    raw = textwrap.dedent(f"""\
        From: Juan Perez <juan@empresa.com>
        To: secretaria@midominio.com
        Subject: Por favor envía el reporte diario
        Date: {now}
        Message-ID: <test-001@empresa.com>
        MIME-Version: 1.0
        Content-Type: text/plain; charset=utf-8

        Hola,
        Necesito el reporte diario de hoy.
        Gracias.
    """)
    return raw.encode("utf-8")


@pytest.fixture
def sample_reply_email_bytes() -> bytes:
    """RFC 5322 email that is a reply (Re: subject)."""
    now = email.utils.formatdate(localtime=False)
    raw = textwrap.dedent(f"""\
        From: Juan Perez <juan@empresa.com>
        To: secretaria@midominio.com
        Subject: Re: Alerta de anomalía detectada
        Date: {now}
        Message-ID: <test-002@empresa.com>
        In-Reply-To: <alerta-001@midominio.com>
        References: <alerta-001@midominio.com>
        MIME-Version: 1.0
        Content-Type: text/plain; charset=utf-8

        Recibido, gracias.
    """)
    return raw.encode("utf-8")
