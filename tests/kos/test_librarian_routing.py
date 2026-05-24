"""
Tests for Librarian routing logic.

Covers semantic routing, OneDrive routing, and MCP routing.
All external calls are mocked.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.librarian.response_builder import LibrarianResponse


@pytest.fixture()
def mock_db():
    db = MagicMock()
    db.cursor.return_value.__enter__ = lambda s: s
    db.cursor.return_value.__exit__ = MagicMock(return_value=False)
    db.cursor.return_value.fetchone.return_value = None
    db.cursor.return_value.fetchall.return_value = []
    return db


@pytest.fixture()
def tenant_id():
    return str(uuid.uuid4())


@pytest.fixture()
def user_id():
    return str(uuid.uuid4())


class TestSemanticRouting:
    @pytest.mark.asyncio
    async def test_high_confidence_semantic_returns_immediately(
        self, mock_db, tenant_id, user_id
    ):
        """When semantic search returns a high-confidence result, routing stops there."""
        from agents.librarian.search_local import ChunkResult  # noqa: PLC0415
        from agents.librarian.router import route_query  # noqa: PLC0415

        mock_chunk = ChunkResult(
            chunk_id=str(uuid.uuid4()),
            document_id=str(uuid.uuid4()),
            filename="policy.pdf",
            section_title="Remote Work Policy",
            content_text="Employees may work remotely up to 3 days per week.",
            content_type="text",
            page_number=4,
            score=0.92,
            search_method="semantic",
            tenant_id=tenant_id,
        )

        with (
            patch("agents.librarian.router.check_query_cache", return_value=None),
            patch("agents.librarian.router.semantic_search", return_value=[mock_chunk]),
            patch("agents.librarian.router._log_query"),
        ):
            response = await route_query(
                query="remote work policy",
                tenant_id=tenant_id,
                user_id=user_id,
                session_context={"session_id": str(uuid.uuid4())},
                db_conn=mock_db,
            )

        assert isinstance(response, LibrarianResponse)
        assert response.confidence >= 0.75
        assert "remote" in response.answer_text.lower() or len(response.citations) > 0

    @pytest.mark.asyncio
    async def test_low_confidence_falls_back_to_fulltext(
        self, mock_db, tenant_id, user_id
    ):
        """Low semantic score triggers fulltext fallback search."""
        from agents.librarian.search_local import ChunkResult  # noqa: PLC0415
        from agents.librarian.router import route_query  # noqa: PLC0415

        low_chunk = ChunkResult(
            chunk_id=str(uuid.uuid4()),
            document_id=str(uuid.uuid4()),
            filename="manual.pdf",
            section_title="Chapter 1",
            content_text="General overview.",
            content_type="text",
            page_number=1,
            score=0.50,  # below threshold
            search_method="semantic",
            tenant_id=tenant_id,
        )
        ft_chunk = ChunkResult(
            chunk_id=str(uuid.uuid4()),
            document_id=str(uuid.uuid4()),
            filename="faq.pdf",
            section_title="FAQ",
            content_text="Frequently asked questions about reimbursement.",
            content_type="text",
            page_number=2,
            score=0.80,
            search_method="fulltext",
            tenant_id=tenant_id,
        )

        with (
            patch("agents.librarian.router.check_query_cache", return_value=None),
            patch("agents.librarian.router.semantic_search", return_value=[low_chunk]),
            patch("agents.librarian.router.fulltext_search", return_value=[ft_chunk]),
            patch("agents.librarian.router._log_query"),
        ):
            response = await route_query(
                query="reimbursement policy",
                tenant_id=tenant_id,
                user_id=user_id,
                session_context={},
                db_conn=mock_db,
            )

        assert "local_fulltext" in response.sources_tried


class TestOneDriveRouting:
    @pytest.mark.asyncio
    async def test_onedrive_keyword_triggers_od_search(
        self, mock_db, tenant_id, user_id
    ):
        """Queries mentioning 'OneDrive' must trigger OneDrive index search."""
        from agents.librarian.router import route_query  # noqa: PLC0415

        with (
            patch("agents.librarian.router.check_query_cache", return_value=None),
            patch("agents.librarian.router.semantic_search", return_value=[]),
            patch("agents.librarian.router.fulltext_search", return_value=[]),
            patch(
                "agents.librarian.router.search_onedrive_index", return_value=[]
            ) as mock_od,
            patch("agents.librarian.router._log_query"),
        ):
            await route_query(
                query="find the contract in my OneDrive",
                tenant_id=tenant_id,
                user_id=user_id,
                session_context={},
                db_conn=mock_db,
            )

        mock_od.assert_called_once()


class TestMcpRouting:
    @pytest.mark.asyncio
    async def test_structured_query_triggers_mcp_lookup(
        self, mock_db, tenant_id, user_id
    ):
        """Queries with structured-data signals must attempt MCP sources."""
        from agents.librarian.router import route_query  # noqa: PLC0415
        from agents.librarian.search_mcp import McpQueryResult  # noqa: PLC0415

        mock_mcp = McpQueryResult(
            ok=True,
            source_name="CRM Clientes",
            source_id=str(uuid.uuid4()),
            data=[{"name": "Acme", "revenue": 50000}],
            result_summary="1 row returned.",
            response_time_ms=120,
        )

        with (
            patch("agents.librarian.router.check_query_cache", return_value=None),
            patch("agents.librarian.router.semantic_search", return_value=[]),
            patch("agents.librarian.router.fulltext_search", return_value=[]),
            patch("agents.librarian.router.search_onedrive_index", return_value=[]),
            patch(
                "agents.librarian.router.query_implies_structured_data",
                return_value=True,
            ),
            patch(
                "agents.librarian.router.find_relevant_source",
                return_value={
                    "id": str(uuid.uuid4()),
                    "name": "CRM Clientes",
                    "mcp_endpoint": "http://mcp:8080",
                    "schema_snapshot": {},
                    "query_examples": [],
                    "credentials_vault_ref": "vault://crm",
                },
            ),
            patch("agents.librarian.router.execute_mcp_query", return_value=mock_mcp),
            patch("agents.librarian.router._log_query"),
        ):
            response = await route_query(
                query="cuántos clientes facturaron más de $1000 el mes pasado",
                tenant_id=tenant_id,
                user_id=user_id,
                session_context={},
                db_conn=mock_db,
            )

        assert "mcp_database" in response.sources_tried
        assert "CRM Clientes" in response.answer_text


class TestAttachedFile:
    @pytest.mark.asyncio
    async def test_attached_file_triggers_ingestion(
        self, mock_db, tenant_id, user_id, tmp_path
    ):
        """When session_context has an attached_file, ingestion is triggered."""
        import fitz  # noqa: PLC0415

        doc = fitz.open()
        doc.new_page()
        path = tmp_path / "upload.pdf"
        doc.save(str(path))
        doc.close()

        from agents.librarian.router import route_query  # noqa: PLC0415

        with (
            patch(
                "agents.librarian.router._trigger_ingestion",
                return_value="test-job-id",
            ) as mock_ingest,
        ):
            response = await route_query(
                query="",
                tenant_id=tenant_id,
                user_id=user_id,
                session_context={
                    "attached_file": {
                        "path": str(path),
                        "type": "pdf",
                        "name": "upload.pdf",
                    }
                },
                db_conn=mock_db,
            )

        mock_ingest.assert_called_once()
        assert "procesando" in response.answer_text.lower() or "processing" in response.answer_text.lower()
