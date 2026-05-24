"""
Librarian routing logic.

Decides where to search and in what order, then delegates to the
appropriate search module.  Every invocation is logged to librarian_queries.

Always enforces tenant isolation — tenant_id is required and checked at
every DB call downstream.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Optional

from .search_local import (
    ChunkResult,
    check_query_cache,
    fulltext_search,
    semantic_search,
)
from .search_mcp import (
    McpQueryResult,
    execute_mcp_query,
    find_relevant_source,
    query_implies_structured_data,
)
from .search_onedrive import (
    fetch_and_process_onedrive_file,
    search_graph_api,
    search_onedrive_index,
)
from .response_builder import LibrarianResponse, build_response

log = logging.getLogger(__name__)

_ONEDRIVE_SIGNALS = re.compile(
    r"\b(onedrive|one\s*drive|drive|mis\s+archivos?|my\s+files?|sharepoint)\b",
    re.I,
)


async def route_query(
    query: str,
    tenant_id: str,
    user_id: str,
    session_context: dict,
    db_conn,
    *,
    microsoft_token: str = "",
    vault_resolver=None,
    queue_job_id: str = "",
) -> LibrarianResponse:
    """
    Main Librarian dispatch.  Async-safe (no async I/O; async signature allows
    integration into async OpenClaw handlers without blocking the event loop via
    run_in_executor).
    """
    t0 = time.monotonic()
    sources_tried: list[str] = []
    chunks: list[ChunkResult] = []
    mcp_result: Optional[McpQueryResult] = None

    # ── Step 1: Attached file ─────────────────────────────────────────────────
    attached = session_context.get("attached_file")
    if attached:
        job_id = _trigger_ingestion(
            file_path=attached["path"],
            file_type=attached.get("type", "pdf"),
            tenant_id=tenant_id,
            user_id=user_id,
            db_conn=db_conn,
            queue_job_id=queue_job_id,
            session_id=session_context.get("session_id", ""),
        )
        # Return immediately; document will be available after processing
        return LibrarianResponse(
            answer_text=(
                f"📥 Recibí tu archivo **{attached.get('name', '')}**. "
                f"Lo estoy procesando (job: `{job_id}`). "
                "Disponible en breve para búsquedas."
            ),
            citations=[],
            confidence=1.0,
            sources_tried=["ingestion"],
            sources_used=["ingestion"],
        )

    # ── Step 2: Cache lookup ──────────────────────────────────────────────────
    cached = check_query_cache(query, tenant_id, db_conn)
    if cached:
        elapsed = int((time.monotonic() - t0) * 1000)
        _log_query(
            db_conn,
            tenant_id=tenant_id,
            session_id=session_context.get("session_id", ""),
            requested_by=user_id,
            query=query,
            sources_tried=["cache"],
            results_found=1,
            sources_used=cached["sources_used"],
            confidence=cached["confidence_score"],
            response_time_ms=elapsed,
        )
        # Reconstruct a minimal response from cache metadata
        return LibrarianResponse(
            answer_text=f"*(resultado en caché)*\n\n{json.dumps(cached['sources_used'], indent=2)}",
            citations=[],
            confidence=cached["confidence_score"],
            sources_tried=["cache"],
            sources_used=list(cached["sources_used"]) if cached["sources_used"] else [],
            from_cache=True,
        )

    # ── Step 3: Semantic search ───────────────────────────────────────────────
    sources_tried.append("local_semantic")
    chunks = semantic_search(query, tenant_id, db_conn)

    if chunks and chunks[0].score >= 0.75:
        return _finish(chunks, sources_tried, tenant_id, t0, db_conn,
                       session_context, user_id, query)

    # ── Step 4: Fulltext fallback ─────────────────────────────────────────────
    sources_tried.append("local_fulltext")
    ft_chunks = fulltext_search(query, tenant_id, db_conn)
    if ft_chunks:
        chunks = (chunks + ft_chunks)[:10]  # merge, deduplicate below
        chunks = _deduplicate(chunks)
        if chunks:
            return _finish(chunks, sources_tried, tenant_id, t0, db_conn,
                           session_context, user_id, query)

    no_local_results = len(chunks) == 0
    onedrive_implied = bool(_ONEDRIVE_SIGNALS.search(query))

    # ── Step 5: OneDrive search ───────────────────────────────────────────────
    if onedrive_implied or no_local_results:
        sources_tried.append("onedrive_index")

        # 5a: local index
        od_rows = search_onedrive_index(query, tenant_id, user_id, db_conn)
        for row in od_rows:
            if row["content_cached"] and row["summary_cache"]:
                # Use cached summary directly as a synthetic chunk
                chunks.append(_od_summary_to_chunk(row, tenant_id))
            elif microsoft_token:
                # Download + process on demand
                od_result = fetch_and_process_onedrive_file(
                    row["onedrive_file_id"], tenant_id, user_id,
                    microsoft_token, db_conn
                )
                if od_result.ok:
                    chunks.append(_od_content_to_chunk(od_result, tenant_id))

        # 5b: live Graph search if token available
        if microsoft_token and not od_rows:
            sources_tried.append("onedrive_graph")
            graph_result = search_graph_api(
                query, tenant_id, user_id, microsoft_token, db_conn
            )
            if graph_result.requires_confirmation:
                # Ask user to confirm before downloading
                filenames = [
                    f for f in graph_result.files_found
                    if f["id"] in graph_result.requires_confirmation
                ]
                names_str = ", ".join(f.get("name", "?") for f in filenames[:3])
                return LibrarianResponse(
                    answer_text=(
                        f"🔍 Encontré archivos en tu OneDrive relacionados con la consulta: "
                        f"**{names_str}**.\n\n"
                        "¿Deseas que los descargue y procese para responderte? "
                        "Responde **sí** para continuar."
                    ),
                    citations=[],
                    confidence=0.6,
                    sources_tried=sources_tried,
                    sources_used=[],
                )

        if chunks:
            return _finish(chunks, sources_tried, tenant_id, t0, db_conn,
                           session_context, user_id, query)

    # ── Step 6: MCP structured data ───────────────────────────────────────────
    if query_implies_structured_data(query):
        sources_tried.append("mcp_database")
        source = find_relevant_source(query, tenant_id, db_conn)
        if source:
            mcp_result = execute_mcp_query(
                query=query,
                source=source,
                tenant_id=tenant_id,
                requested_by=user_id or "librarian_agent",
                db_conn=db_conn,
                vault_resolver=vault_resolver,
            )
            if mcp_result.ok:
                return _finish(chunks, sources_tried, tenant_id, t0, db_conn,
                               session_context, user_id, query,
                               mcp_result=mcp_result)

    # ── Step 7: Not found ─────────────────────────────────────────────────────
    elapsed = int((time.monotonic() - t0) * 1000)
    _log_query(
        db_conn,
        tenant_id=tenant_id,
        session_id=session_context.get("session_id", ""),
        requested_by=user_id,
        query=query,
        sources_tried=sources_tried,
        results_found=0,
        sources_used=[],
        confidence=0.0,
        response_time_ms=elapsed,
    )

    suggestions = []
    if "onedrive_index" not in sources_tried and not microsoft_token:
        suggestions.append("Conecta tu cuenta OneDrive para buscar en tus archivos.")
    if not query_implies_structured_data(query):
        suggestions.append("Si buscas datos de negocio, prueba con términos más específicos.")

    suggestion_text = "\n".join(f"• {s}" for s in suggestions)
    return LibrarianResponse(
        answer_text=(
            f"No encontré información relevante sobre: *{query}*\n\n"
            f"Fuentes consultadas: {', '.join(sources_tried)}\n\n"
            + (f"**Sugerencias:**\n{suggestion_text}" if suggestion_text else "")
        ),
        citations=[],
        confidence=0.0,
        sources_tried=sources_tried,
        sources_used=[],
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _finish(
    chunks: list[ChunkResult],
    sources_tried: list[str],
    tenant_id: str,
    t0: float,
    db_conn,
    session_context: dict,
    user_id: str,
    query: str,
    *,
    mcp_result=None,
) -> LibrarianResponse:
    response = build_response(
        chunks=chunks,
        sources_tried=sources_tried,
        tenant_id=tenant_id,
        mcp_result=mcp_result,
    )
    elapsed = int((time.monotonic() - t0) * 1000)
    _log_query(
        db_conn,
        tenant_id=tenant_id,
        session_id=session_context.get("session_id", ""),
        requested_by=user_id,
        query=query,
        sources_tried=sources_tried,
        results_found=len(chunks),
        sources_used=response.sources_used,
        confidence=response.confidence,
        response_time_ms=elapsed,
    )
    return response


def _trigger_ingestion(
    file_path: str,
    file_type: str,
    tenant_id: str,
    user_id: str,
    db_conn,
    queue_job_id: str,
    session_id: str,
) -> str:
    """Enqueue a document ingestion job and return the job ID."""
    from services.queue.tasks import process_document  # noqa: PLC0415

    job_id = str(uuid.uuid4())
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_queue
                    (id, tenant_id, file_path, file_type, source_type,
                     requested_by_user_id, status)
                VALUES (%s, %s, %s, %s, 'local_upload', %s, 'queued')
                """,
                (job_id, tenant_id, file_path, file_type, user_id),
            )
        db_conn.commit()
    except Exception as exc:
        log.error("Could not enqueue ingestion job: %s", exc)

    process_document.apply_async(
        kwargs={
            "file_path": file_path,
            "file_type": file_type,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "source_type": "local_upload",
            "queue_job_id": job_id,
            "session_id": session_id,
        }
    )
    return job_id


def _od_summary_to_chunk(row: dict, tenant_id: str) -> ChunkResult:
    from .search_local import ChunkResult  # noqa: PLC0415
    return ChunkResult(
        chunk_id=row["id"],
        document_id=row.get("document_id") or "",
        filename=row["filename"] or "",
        section_title="OneDrive summary",
        content_text=row["summary_cache"] or "",
        content_type="text",
        page_number=None,
        score=0.70,
        search_method="onedrive_index",
        tenant_id=tenant_id,
    )


def _od_content_to_chunk(od_result, tenant_id: str) -> ChunkResult:
    from .search_local import ChunkResult  # noqa: PLC0415
    return ChunkResult(
        chunk_id=od_result.onedrive_file_id,
        document_id="",
        filename=od_result.filename,
        section_title="OneDrive on-demand",
        content_text=od_result.content_text[:2000],
        content_type="text",
        page_number=None,
        score=0.72,
        search_method="onedrive_graph",
        tenant_id=tenant_id,
    )


def _deduplicate(chunks: list[ChunkResult]) -> list[ChunkResult]:
    seen: set[str] = set()
    result = []
    for c in chunks:
        if c.chunk_id not in seen:
            seen.add(c.chunk_id)
            result.append(c)
    return result


def _log_query(
    db_conn,
    *,
    tenant_id: str,
    session_id: str,
    requested_by: str,
    query: str,
    sources_tried: list[str],
    results_found: int,
    sources_used: list,
    confidence: float,
    response_time_ms: int,
) -> None:
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO librarian_queries
                    (id, tenant_id, session_id, requested_by, original_query,
                     sources_searched, results_found, sources_used,
                     confidence_score, response_time_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid.uuid4()),
                    tenant_id,
                    session_id or None,
                    requested_by or "unknown",
                    query,
                    json.dumps(sources_tried),
                    results_found,
                    json.dumps(sources_used),
                    confidence,
                    response_time_ms,
                ),
            )
        db_conn.commit()
    except Exception as exc:
        log.warning("librarian_queries log error: %s", exc)
