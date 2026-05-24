"""
Shared fixtures for KOS tests.

Tests run against a real PostgreSQL + pgvector instance via
KOS_TEST_DB_DSN environment variable (defaults to a local Docker service).

No LLM calls are made in any test.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import psycopg2
import pytest

TEST_DB_DSN = os.getenv(
    "KOS_TEST_DB_DSN",
    "postgresql://openclaw:openclaw@localhost:5432/openclaw_test",
)
TEST_TENANT_A = str(uuid.uuid4())
TEST_TENANT_B = str(uuid.uuid4())
TEST_USER_A = str(uuid.uuid4())
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def db_conn():
    conn = psycopg2.connect(TEST_DB_DSN)
    try:
        from pgvector.psycopg2 import register_vector  # noqa: PLC0415
        register_vector(conn)
    except ImportError:
        pass
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def clean_test_data(db_conn):
    """Wipe all KOS tables before each test."""
    tables = [
        "document_chunks", "document_figures", "document_metadata",
        "documents", "knowledge_sources", "ingestion_queue",
        "librarian_queries", "mcp_query_log", "mcp_sources",
        "onedrive_index",
    ]
    with db_conn.cursor() as cur:
        for table in tables:
            cur.execute(f"DELETE FROM {table}")  # noqa: S608
    db_conn.commit()
    yield


@pytest.fixture()
def tenant_a():
    return TEST_TENANT_A


@pytest.fixture()
def tenant_b():
    return TEST_TENANT_B


@pytest.fixture()
def sample_pdf(tmp_path) -> Path:
    """Create a minimal valid PDF with selectable text."""
    import fitz  # noqa: PLC0415
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello KOS. This is a test document about invoices.")
    path = tmp_path / "sample.pdf"
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture()
def eicar_file(tmp_path) -> Path:
    """EICAR anti-malware test string (safe, universally detected by ClamAV)."""
    eicar = (
        b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    )
    p = tmp_path / "eicar.pdf"  # wrong extension on purpose — MIME check fails first
    p.write_bytes(eicar)
    return p
