"""
Stage 2 — Canonicalization and storage.

Transforms an ExtractedDocument into:
  • canonical.md + metadata.json + raw.json on disk
  • rows in documents, document_metadata, document_chunks, document_figures in PostgreSQL
  • vector embeddings in the embedding column of document_chunks (pgvector)

All DB mutations run inside a single transaction — partial failures roll back.
Zero LLM calls.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

KNOWLEDGE_STORE_ROOT = Path(os.getenv("KOS_KNOWLEDGE_STORE_ROOT", "/app/knowledge_store"))
EMBEDDING_MODEL = os.getenv("KOS_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_BATCH_SIZE = int(os.getenv("KOS_EMBEDDING_BATCH_SIZE", "32"))
CHUNK_MAX_WORDS = int(os.getenv("KOS_CHUNK_MAX_WORDS", "800"))

# Sentence-transformers model is loaded once and reused (thread-safe after first load).
_encoder = None


def _get_encoder():
    global _encoder  # noqa: PLW0603
    if _encoder is None:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        _encoder = SentenceTransformer(EMBEDDING_MODEL)
        log.info("Loaded embedding model: %s", EMBEDDING_MODEL)
    return _encoder


# ── Public entry point ─────────────────────────────────────────────────────────

def canonicalize_and_store(
    extracted,                          # ExtractedDocument from stage 1
    tenant_id: str,
    file_hash: str,
    filename_original: str,
    file_type: str,
    source_id: Optional[str],
    db_conn,                            # PEP-249 connection
) -> str:
    """
    Persist an ExtractedDocument.  Returns the new document UUID.

    Raises on any unrecoverable error; the caller (pipeline.py) rolls back.
    """
    doc_id = str(uuid.uuid4())
    canonical_dir = KNOWLEDGE_STORE_ROOT / tenant_id / doc_id
    canonical_dir.mkdir(parents=True, exist_ok=True)

    # ── 2.1  Build canonical object ────────────────────────────────────────────
    canonical_obj = _build_canonical_object(
        doc_id, file_hash, tenant_id, filename_original,
        file_type, extracted, canonical_dir,
    )

    # ── 2.2  Write to disk ─────────────────────────────────────────────────────
    _write_disk(canonical_obj, extracted, canonical_dir)

    # ── 2.3  Semantic chunking ─────────────────────────────────────────────────
    chunks = _build_chunks(extracted, doc_id, tenant_id)

    # ── 2.4  Generate embeddings (CPU, batched) ────────────────────────────────
    _embed_chunks(chunks)

    # ── 2.5  Persist to PostgreSQL (single transaction) ───────────────────────
    with db_conn:
        with db_conn.cursor() as cur:
            _insert_document(cur, doc_id, source_id, tenant_id, file_hash,
                             filename_original, file_type, canonical_obj,
                             canonical_dir, extracted)
            _insert_metadata(cur, doc_id, canonical_obj["metadata"])
            _insert_chunks(cur, chunks)
            _insert_figures(cur, doc_id, canonical_dir, extracted)

    log.info("Document %s canonicalised (%d chunks)", doc_id, len(chunks))
    return doc_id


# ── 2.1  Canonical object ──────────────────────────────────────────────────────

def _build_canonical_object(
    doc_id: str,
    file_hash: str,
    tenant_id: str,
    filename_original: str,
    file_type: str,
    extracted,
    canonical_dir: Path,
) -> dict:
    figures_meta = [
        {
            "index": i,
            "caption": fig.caption,
            "page": fig.page,
            "image_path": str(canonical_dir / "figures" / f"figure_{i:03d}.png"),
        }
        for i, fig in enumerate(extracted.figures)
    ]

    return {
        "id": doc_id,
        "hash": file_hash,
        "tenant_id": tenant_id,
        "filename_original": filename_original,
        "file_type": file_type,
        "metadata": {
            "title": extracted.metadata.get("title") or filename_original,
            "authors": extracted.metadata.get("authors", []),
            "date_created": extracted.metadata.get("date_created"),
            "date_modified": extracted.metadata.get("date_modified"),
            "organization": extracted.metadata.get("organization"),
            "keywords": extracted.metadata.get("keywords", []),
            "subject": extracted.metadata.get("subject"),
        },
        "sections": [
            {"title": s.title, "level": s.level, "content": s.content[:500], "page": s.page}
            for s in extracted.sections
        ],
        "tables": [
            {"title": t.title, "data": t.data[:50], "page": t.page}  # cap at 50 rows in JSON
            for t in extracted.tables
        ],
        "figures": figures_meta,
        "processing_date": datetime.now(timezone.utc).isoformat(),
        "source_tool": extracted.source_tool,
        "language": extracted.language,
        "is_scanned": extracted.is_scanned,
    }


# ── 2.2  Disk storage ──────────────────────────────────────────────────────────

def _write_disk(canonical_obj: dict, extracted, canonical_dir: Path) -> None:
    # canonical.md
    (canonical_dir / "canonical.md").write_text(extracted.markdown, encoding="utf-8")

    # metadata.json
    (canonical_dir / "metadata.json").write_text(
        json.dumps(canonical_obj["metadata"], indent=2, default=str), encoding="utf-8"
    )

    # raw.json  (full canonical minus figures bytes)
    (canonical_dir / "raw.json").write_text(
        json.dumps(canonical_obj, indent=2, default=str), encoding="utf-8"
    )

    # figures/
    figures_dir = canonical_dir / "figures"
    if extracted.figures:
        figures_dir.mkdir(exist_ok=True)
        for i, fig in enumerate(extracted.figures):
            fig_path = figures_dir / f"figure_{i:03d}.png"
            fig_path.write_bytes(fig.image_bytes)


# ── 2.3  Semantic chunking ─────────────────────────────────────────────────────

def _build_chunks(extracted, doc_id: str, tenant_id: str) -> list[dict]:
    """
    Split sections into retrievable chunks.

    Strategy (in order):
    1. One chunk per section that fits within CHUNK_MAX_WORDS.
    2. If a section exceeds CHUNK_MAX_WORDS, split by paragraph (blank lines).
    3. Tables → one chunk each (content_type='table').
    4. Figure captions → one chunk each (content_type='figure_caption').
    """
    chunks: list[dict] = []
    idx = 0

    # Text sections
    for section in extracted.sections:
        words = section.content.split()
        if len(words) <= CHUNK_MAX_WORDS:
            chunks.append(_make_chunk(
                idx, doc_id, tenant_id, section.content,
                content_type="header" if section.level <= 1 else "text",
                section_title=section.title,
                page=section.page,
            ))
            idx += 1
        else:
            # Split by paragraph
            paragraphs = [p.strip() for p in section.content.split("\n\n") if p.strip()]
            buffer: list[str] = []
            buf_words = 0
            for para in paragraphs:
                pw = len(para.split())
                if buf_words + pw > CHUNK_MAX_WORDS and buffer:
                    chunks.append(_make_chunk(
                        idx, doc_id, tenant_id, "\n\n".join(buffer),
                        content_type="text",
                        section_title=section.title,
                        page=section.page,
                    ))
                    idx += 1
                    buffer, buf_words = [], 0
                buffer.append(para)
                buf_words += pw
            if buffer:
                chunks.append(_make_chunk(
                    idx, doc_id, tenant_id, "\n\n".join(buffer),
                    content_type="text",
                    section_title=section.title,
                    page=section.page,
                ))
                idx += 1

    # Tables
    for table in extracted.tables:
        # Serialise table rows as tab-separated text for embedding
        rows_text = "\n".join("\t".join(str(c) for c in row) for row in table.data[:200])
        content = f"[Table: {table.title}]\n{rows_text}" if table.title else rows_text
        chunks.append(_make_chunk(
            idx, doc_id, tenant_id, content,
            content_type="table",
            section_title=table.title or "Table",
            page=table.page,
        ))
        idx += 1

    # Figure captions
    for fig in extracted.figures:
        if fig.caption:
            chunks.append(_make_chunk(
                idx, doc_id, tenant_id, fig.caption,
                content_type="figure_caption",
                section_title=f"Figure {fig.index}",
                page=fig.page,
            ))
            idx += 1

    return chunks


def _make_chunk(
    idx: int,
    doc_id: str,
    tenant_id: str,
    content: str,
    *,
    content_type: str,
    section_title: str,
    page: Optional[int],
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "document_id": doc_id,
        "tenant_id": tenant_id,
        "chunk_index": idx,
        "section_title": section_title,
        "content_text": content,
        "content_type": content_type,
        "page_number": page,
        "char_start": None,
        "char_end": None,
        "embedding": None,              # filled in stage 2.4
    }


# ── 2.4  Embedding generation ──────────────────────────────────────────────────

def _embed_chunks(chunks: list[dict]) -> None:
    """Fill the ``embedding`` field for every chunk in-place (batched CPU)."""
    if not chunks:
        return

    encoder = _get_encoder()
    texts = [c["content_text"] for c in chunks]

    for batch_start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[batch_start: batch_start + EMBEDDING_BATCH_SIZE]
        vectors = encoder.encode(
            batch,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        for i, vec in enumerate(vectors):
            chunks[batch_start + i]["embedding"] = vec.tolist()

    log.debug("Embedded %d chunks", len(chunks))


# ── 2.5  DB inserts ────────────────────────────────────────────────────────────

def _insert_document(
    cur,
    doc_id: str,
    source_id: Optional[str],
    tenant_id: str,
    file_hash: str,
    filename_original: str,
    file_type: str,
    canonical_obj: dict,
    canonical_dir: Path,
    extracted,
) -> None:
    cur.execute(
        """
        INSERT INTO documents
            (id, source_id, tenant_id, hash_sha256, filename_original, file_type,
             page_count, language_detected, processing_status, canonical_path,
             processed_at, version_number, security_scan_status)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, 'processing', %s, NOW(), 1, 'clean')
        ON CONFLICT (hash_sha256) DO NOTHING
        """,
        (
            doc_id,
            source_id,
            tenant_id,
            file_hash,
            filename_original,
            file_type,
            len(extracted.sections),   # approximate; real page_count set later
            extracted.language,
            str(canonical_dir),
        ),
    )


def _insert_metadata(cur, doc_id: str, meta: dict) -> None:
    cur.execute(
        """
        INSERT INTO document_metadata
            (id, document_id, title, authors, date_created, date_modified,
             organization, keywords, subject)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            str(uuid.uuid4()),
            doc_id,
            meta.get("title"),
            json.dumps(meta.get("authors") or []),
            meta.get("date_created"),
            meta.get("date_modified"),
            meta.get("organization"),
            json.dumps(meta.get("keywords") or []),
            meta.get("subject"),
        ),
    )


def _insert_chunks(cur, chunks: list[dict]) -> None:
    if not chunks:
        return

    # pgvector expects the vector as a Python list or a '[…]' string literal
    rows = [
        (
            c["id"],
            c["document_id"],
            c["tenant_id"],
            c["chunk_index"],
            c["section_title"],
            c["content_text"],
            c["content_type"],
            c["page_number"],
            c["char_start"],
            c["char_end"],
            c["embedding"],             # psycopg2-binary + pgvector adapter handles list→vector
        )
        for c in chunks
    ]

    cur.executemany(
        """
        INSERT INTO document_chunks
            (id, document_id, tenant_id, chunk_index, section_title,
             content_text, content_type, page_number, char_start, char_end, embedding)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
        """,
        rows,
    )


def _insert_figures(cur, doc_id: str, canonical_dir: Path, extracted) -> None:
    for i, fig in enumerate(extracted.figures):
        img_path = str(canonical_dir / "figures" / f"figure_{i:03d}.png")
        cur.execute(
            """
            INSERT INTO document_figures
                (id, document_id, figure_index, caption, image_path, page_number, ocr_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(uuid.uuid4()),
                doc_id,
                i,
                fig.caption or "",
                img_path,
                fig.page,
                None,   # OCR on figures is a future enhancement
            ),
        )
