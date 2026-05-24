"""
Tests for Stage 2 — canonicalization.

Verifies:
- All chunks have embeddings
- No duplicate chunks by hash
- Files are written to disk
- DB rows are inserted correctly
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
import pytest

from services.ingestion.stage_1_extraction import extract_structure
from services.ingestion.stage_2_canonicalize import (
    _build_chunks,
    _embed_chunks,
    canonicalize_and_store,
)


class TestChunking:
    def test_chunks_created_from_sections(self, sample_pdf):
        extracted = extract_structure(str(sample_pdf), "pdf")
        doc_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())
        chunks = _build_chunks(extracted, doc_id, tenant_id)
        assert len(chunks) >= 1

    def test_each_chunk_has_required_fields(self, sample_pdf):
        extracted = extract_structure(str(sample_pdf), "pdf")
        doc_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())
        chunks = _build_chunks(extracted, doc_id, tenant_id)
        for c in chunks:
            assert c["content_text"]
            assert c["document_id"] == doc_id
            assert c["tenant_id"] == tenant_id
            assert c["content_type"] in {"text","table","figure_caption","header","list"}

    def test_long_section_split_into_multiple_chunks(self, tmp_path):
        """Sections exceeding CHUNK_MAX_WORDS must produce multiple chunks."""
        doc = fitz.open()
        page = doc.new_page()
        # 1200 words
        long_text = " ".join(["word"] * 1200)
        page.insert_text((72, 72), long_text)
        path = tmp_path / "long.pdf"
        doc.save(str(path))
        doc.close()

        extracted = extract_structure(str(path), "pdf")
        doc_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())

        with patch("services.ingestion.stage_2_canonicalize.CHUNK_MAX_WORDS", 400):
            chunks = _build_chunks(extracted, doc_id, tenant_id)

        assert len(chunks) >= 2


class TestEmbedding:
    def test_all_chunks_receive_embeddings(self, sample_pdf):
        extracted = extract_structure(str(sample_pdf), "pdf")
        doc_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())
        chunks = _build_chunks(extracted, doc_id, tenant_id)
        _embed_chunks(chunks)

        for c in chunks:
            assert c["embedding"] is not None, f"Chunk {c['chunk_index']} missing embedding"
            assert len(c["embedding"]) == 768

    def test_embedding_is_normalised(self, sample_pdf):
        """All-MiniLM-L6-v2 with normalize_embeddings=True should give unit vectors."""
        import math  # noqa: PLC0415

        extracted = extract_structure(str(sample_pdf), "pdf")
        chunks = _build_chunks(extracted, str(uuid.uuid4()), str(uuid.uuid4()))
        _embed_chunks(chunks)

        for c in chunks[:3]:
            norm = math.sqrt(sum(x * x for x in c["embedding"]))
            assert abs(norm - 1.0) < 0.01, f"Vector not normalised: {norm}"


class TestFullPipeline:
    @pytest.mark.integration
    def test_canonicalize_writes_files_and_db(self, sample_pdf, db_conn, tenant_a, tmp_path):
        """Integration test: full stage 2 against a real DB."""
        extracted = extract_structure(str(sample_pdf), "pdf")
        file_hash = "a" * 64  # synthetic hash

        with patch(
            "services.ingestion.stage_2_canonicalize.KNOWLEDGE_STORE_ROOT",
            tmp_path,
        ):
            doc_id = canonicalize_and_store(
                extracted=extracted,
                tenant_id=tenant_a,
                file_hash=file_hash,
                filename_original="sample.pdf",
                file_type="pdf",
                source_id=None,
                db_conn=db_conn,
            )

        assert doc_id

        # Verify disk
        canonical_dir = tmp_path / tenant_a / doc_id
        assert (canonical_dir / "canonical.md").exists()
        assert (canonical_dir / "metadata.json").exists()

        # Verify DB
        with db_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM document_chunks WHERE document_id = %s",
                        (doc_id,))
            count = cur.fetchone()[0]
        assert count >= 1

    @pytest.mark.integration
    def test_no_duplicate_hash_in_db(self, sample_pdf, db_conn, tenant_a, tmp_path):
        """Inserting the same hash twice should silently skip the second insert."""
        extracted = extract_structure(str(sample_pdf), "pdf")
        file_hash = "b" * 64

        with patch(
            "services.ingestion.stage_2_canonicalize.KNOWLEDGE_STORE_ROOT",
            tmp_path,
        ):
            id1 = canonicalize_and_store(
                extracted=extracted,
                tenant_id=tenant_a,
                file_hash=file_hash,
                filename_original="dup.pdf",
                file_type="pdf",
                source_id=None,
                db_conn=db_conn,
            )
            # Second call with same hash — ON CONFLICT DO NOTHING
            id2 = canonicalize_and_store(
                extracted=extracted,
                tenant_id=tenant_a,
                file_hash=file_hash,
                filename_original="dup.pdf",
                file_type="pdf",
                source_id=None,
                db_conn=db_conn,
            )

        with db_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM documents WHERE hash_sha256 = %s",
                        (file_hash,))
            count = cur.fetchone()[0]

        assert count == 1  # only one row despite two calls
