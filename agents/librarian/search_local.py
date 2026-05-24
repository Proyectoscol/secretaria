"""
Local knowledge search — semantic vector search + PostgreSQL fulltext fallback.

Tenant isolation is enforced at every query.  A chunk belonging to tenant A
can never appear in a query from tenant B.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

EMBEDDING_MODEL = os.getenv("KOS_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
SEMANTIC_THRESHOLD = float(os.getenv("KOS_SEMANTIC_THRESHOLD", "0.75"))
TOP_K = int(os.getenv("KOS_TOP_K", "5"))

_encoder = None


def _get_encoder():
    global _encoder  # noqa: PLW0603
    if _encoder is None:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        _encoder = SentenceTransformer(EMBEDDING_MODEL)
    return _encoder


@dataclass
class ChunkResult:
    chunk_id: str
    document_id: str
    filename: str
    section_title: str
    content_text: str
    content_type: str
    page_number: Optional[int]
    score: float                    # cosine similarity or FTS rank
    search_method: str              # 'semantic' | 'fulltext'
    tenant_id: str = ""             # populated by all search functions for isolation guard


def semantic_search(
    query: str,
    tenant_id: str,
    db_conn,
    *,
    top_k: int = TOP_K,
    threshold: float = SEMANTIC_THRESHOLD,
) -> list[ChunkResult]:
    """
    Embed the query and retrieve nearest chunks via HNSW cosine search.
    Only chunks belonging to ``tenant_id`` are returned.
    """
    encoder = _get_encoder()
    query_vec = encoder.encode(query, normalize_embeddings=True).tolist()

    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    dc.id,
                    dc.document_id,
                    d.filename_original,
                    dc.section_title,
                    dc.content_text,
                    dc.content_type,
                    dc.page_number,
                    1 - (dc.embedding <=> %s::vector) AS score
                FROM document_chunks dc
                JOIN documents d ON d.id = dc.document_id
                WHERE dc.tenant_id = %s
                  AND d.processing_status = 'done'
                  AND 1 - (dc.embedding <=> %s::vector) >= %s
                ORDER BY dc.embedding <=> %s::vector
                LIMIT %s
                """,
                (query_vec, tenant_id, query_vec, threshold, query_vec, top_k),
            )
            rows = cur.fetchall()
    except Exception as exc:
        log.error("Semantic search error: %s", exc)
        return []

    return [
        ChunkResult(
            chunk_id=str(r[0]),
            document_id=str(r[1]),
            filename=r[2] or "",
            section_title=r[3] or "",
            content_text=r[4],
            content_type=r[5],
            page_number=r[6],
            score=float(r[7]),
            search_method="semantic",
            tenant_id=tenant_id,
        )
        for r in rows
    ]


def fulltext_search(
    query: str,
    tenant_id: str,
    db_conn,
    *,
    top_k: int = TOP_K,
) -> list[ChunkResult]:
    """
    PostgreSQL FTS via to_tsvector / plainto_tsquery.
    Used as a fallback when semantic similarity is below threshold.
    """
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    dc.id,
                    dc.document_id,
                    d.filename_original,
                    dc.section_title,
                    dc.content_text,
                    dc.content_type,
                    dc.page_number,
                    ts_rank(to_tsvector('simple', dc.content_text),
                            plainto_tsquery('simple', %s)) AS rank
                FROM document_chunks dc
                JOIN documents d ON d.id = dc.document_id
                WHERE dc.tenant_id = %s
                  AND d.processing_status = 'done'
                  AND to_tsvector('simple', dc.content_text)
                      @@ plainto_tsquery('simple', %s)
                ORDER BY rank DESC
                LIMIT %s
                """,
                (query, tenant_id, query, top_k),
            )
            rows = cur.fetchall()
    except Exception as exc:
        log.error("Fulltext search error: %s", exc)
        return []

    return [
        ChunkResult(
            chunk_id=str(r[0]),
            document_id=str(r[1]),
            filename=r[2] or "",
            section_title=r[3] or "",
            content_text=r[4],
            content_type=r[5],
            page_number=r[6],
            score=float(r[7]),
            search_method="fulltext",
            tenant_id=tenant_id,
        )
        for r in rows
    ]


def check_query_cache(
    query: str,
    tenant_id: str,
    db_conn,
    *,
    max_age_hours: int = 2,
    min_confidence: float = 0.8,
) -> Optional[dict]:
    """
    Look for a recent identical query in librarian_queries with high confidence.
    Returns the cached sources_used dict or None.
    """
    try:
        with db_conn.cursor() as cur:
            # Use make_interval() so psycopg2 can safely bind the hours value.
            # INTERVAL '%s hours' does NOT work — the placeholder is inside a
            # string literal and psycopg2 will not substitute it there.
            cur.execute(
                """
                SELECT sources_used, confidence_score
                FROM librarian_queries
                WHERE tenant_id = %s
                  AND original_query = %s
                  AND confidence_score >= %s
                  AND created_at >= NOW() - make_interval(hours => %s)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (tenant_id, query, min_confidence, max_age_hours),
            )
            row = cur.fetchone()
            return {"sources_used": row[0], "confidence_score": row[1]} if row else None
    except Exception as exc:
        log.warning("Cache lookup error: %s", exc)
        return None
