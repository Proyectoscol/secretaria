"""
Multi-tenancy isolation tests.

Tenant A must NEVER see data belonging to Tenant B, regardless of query method.
These tests are the most critical correctness tests in the entire KOS suite.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import fitz
import psycopg2
import pytest

from services.ingestion.stage_1_extraction import extract_structure
from services.ingestion.stage_2_canonicalize import (
    _build_chunks,
    _embed_chunks,
    canonicalize_and_store,
)
from agents.librarian.search_local import semantic_search, fulltext_search


def _insert_tenant_document(
    db_conn,
    tenant_id: str,
    text: str,
    tmp_path: Path,
    filename: str = "doc.pdf",
) -> str:
    """Create a real ingested document for a tenant and return doc_id."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    path = tmp_path / filename
    doc.save(str(path))
    doc.close()

    extracted = extract_structure(str(path), "pdf")
    file_hash = str(uuid.uuid4()).replace("-", "")[:64]  # synthetic unique hash

    with patch(
        "services.ingestion.stage_2_canonicalize.KNOWLEDGE_STORE_ROOT",
        tmp_path / "store",
    ):
        doc_id = canonicalize_and_store(
            extracted=extracted,
            tenant_id=tenant_id,
            file_hash=file_hash,
            filename_original=filename,
            file_type="pdf",
            source_id=None,
            db_conn=db_conn,
        )

    # Mark as done
    with db_conn.cursor() as cur:
        cur.execute(
            "UPDATE documents SET processing_status = 'done' WHERE id = %s",
            (doc_id,),
        )
    db_conn.commit()
    return doc_id


@pytest.mark.integration
class TestTenantIsolation:
    def test_semantic_search_does_not_leak_across_tenants(
        self, db_conn, tenant_a, tenant_b, tmp_path
    ):
        """
        Tenant A ingests a document with a unique keyword.
        Tenant B searches for that keyword.
        Tenant B must receive zero results.
        """
        unique_keyword = f"CONFIDENTIAL_DATA_{uuid.uuid4().hex[:8]}"

        # Tenant A ingests the document
        _insert_tenant_document(
            db_conn, tenant_a,
            f"This document belongs to Tenant A. {unique_keyword}.",
            tmp_path,
            "tenant_a_secret.pdf",
        )

        # Tenant B searches — must get nothing
        results = semantic_search(unique_keyword, tenant_b, db_conn)
        assert results == [], (
            f"TENANT ISOLATION FAILURE: Tenant B got {len(results)} results "
            f"for Tenant A's keyword '{unique_keyword}'"
        )

    def test_fulltext_search_does_not_leak_across_tenants(
        self, db_conn, tenant_a, tenant_b, tmp_path
    ):
        unique_keyword = f"SECRETPHRASE_{uuid.uuid4().hex[:8]}"

        _insert_tenant_document(
            db_conn, tenant_a,
            f"Proprietary information. {unique_keyword}.",
            tmp_path,
            "tenant_a_secret2.pdf",
        )

        results = fulltext_search(unique_keyword, tenant_b, db_conn)
        assert results == [], (
            f"FULLTEXT ISOLATION FAILURE: Tenant B got {len(results)} results"
        )

    def test_tenant_sees_own_data(
        self, db_conn, tenant_a, tmp_path
    ):
        """Tenant A must be able to retrieve its own documents."""
        unique_keyword = f"OWNDATA_{uuid.uuid4().hex[:8]}"

        _insert_tenant_document(
            db_conn, tenant_a,
            f"My own data. {unique_keyword}.",
            tmp_path,
            "tenant_a_own.pdf",
        )

        # Semantic search
        sem_results = semantic_search(unique_keyword, tenant_a, db_conn, threshold=0.0)
        ft_results = fulltext_search(unique_keyword, tenant_a, db_conn)

        assert len(sem_results) > 0 or len(ft_results) > 0, (
            "Tenant A cannot find its own document"
        )

    def test_two_tenants_same_query_different_results(
        self, db_conn, tenant_a, tenant_b, tmp_path
    ):
        """Both tenants have documents but different content — results must not mix."""
        _insert_tenant_document(
            db_conn, tenant_a,
            "Contract for services rendered by Alpha Corp.",
            tmp_path,
            "alpha_contract.pdf",
        )
        _insert_tenant_document(
            db_conn, tenant_b,
            "Agreement for Beta Ltd regarding software licensing.",
            tmp_path / "beta",
            "beta_agreement.pdf",
        )

        results_a = semantic_search("contract services", tenant_a, db_conn, threshold=0.0)
        results_b = semantic_search("contract services", tenant_b, db_conn, threshold=0.0)

        # No result from tenant A should appear in tenant B's results
        ids_a = {r.chunk_id for r in results_a}
        ids_b = {r.chunk_id for r in results_b}
        assert ids_a.isdisjoint(ids_b), "Chunk IDs leaked across tenants"

        # Each result must carry the correct tenant_id
        for r in results_a:
            assert r.tenant_id == tenant_a
        for r in results_b:
            assert r.tenant_id == tenant_b
