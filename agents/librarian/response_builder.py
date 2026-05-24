"""
Response builder — assembles a cited answer from retrieved chunks.

Never mixes chunks from different tenants (guard enforced here).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Citation:
    filename: str
    section_title: str
    page: Optional[int]
    score: float
    search_method: str
    document_id: str = ""   # populated by build_response for API serialization


@dataclass
class LibrarianResponse:
    answer_text: str
    citations: list[Citation]
    confidence: float
    sources_tried: list[str]
    sources_used: list[str]
    from_cache: bool = False


def build_response(
    chunks: list,                   # list[ChunkResult] from search_local or similar
    sources_tried: list[str],
    tenant_id: str,
    *,
    from_cache: bool = False,
    mcp_result=None,                # Optional McpQueryResult
) -> LibrarianResponse:
    """
    Compose a structured response with inline citations.

    ``tenant_id`` is verified against each chunk — mismatches are silently
    dropped (belt-and-suspenders guard on top of SQL-level isolation).
    """
    # Enforce tenant isolation
    safe_chunks = [c for c in chunks if c.tenant_id == tenant_id]
    if len(safe_chunks) < len(chunks):
        import logging
        logging.getLogger(__name__).error(
            "TENANT ISOLATION VIOLATION: %d chunks dropped",
            len(chunks) - len(safe_chunks),
        )

    if not safe_chunks and not mcp_result:
        return LibrarianResponse(
            answer_text="",
            citations=[],
            confidence=0.0,
            sources_tried=sources_tried,
            sources_used=[],
        )

    # Build answer body
    parts: list[str] = []
    citations: list[Citation] = []
    sources_used: list[str] = []

    for chunk in safe_chunks:
        cit = Citation(
            filename=chunk.filename,
            section_title=chunk.section_title,
            page=chunk.page_number,
            score=chunk.score,
            search_method=chunk.search_method,
            document_id=chunk.document_id,
        )
        citations.append(cit)

        page_ref = f", Página {chunk.page_number}" if chunk.page_number else ""
        tag = (
            f"[Fuente: **{chunk.filename}**, "
            f"Sección: *{chunk.section_title}*{page_ref}]"
        )
        parts.append(f"{chunk.content_text}\n\n{tag}")
        if chunk.filename not in sources_used:
            sources_used.append(chunk.filename)

    # Append MCP structured data if present
    if mcp_result and mcp_result.ok:
        parts.append(
            f"**Datos estructurados de {mcp_result.source_name}:**\n\n"
            f"{mcp_result.result_summary}"
        )
        sources_used.append(f"mcp:{mcp_result.source_name}")

    # Confidence = mean score of semantic hits; default 0.7 for FTS-only
    semantic_scores = [c.score for c in citations if c.search_method == "semantic"]
    if semantic_scores:
        confidence = sum(semantic_scores) / len(semantic_scores)
    elif citations:
        confidence = 0.70
    else:
        confidence = 0.50 if mcp_result and mcp_result.ok else 0.0

    answer_text = "\n\n---\n\n".join(parts)
    if from_cache:
        answer_text = f"*(resultado en caché)*\n\n{answer_text}"

    return LibrarianResponse(
        answer_text=answer_text,
        citations=citations,
        confidence=confidence,
        sources_tried=sources_tried,
        sources_used=sources_used,
        from_cache=from_cache,
    )


def format_for_agent(response: LibrarianResponse) -> str:
    """
    Serialize a LibrarianResponse to a compact string suitable for
    injection into another agent's context.
    """
    if not response.answer_text:
        return (
            f"[Bibliotecario] No se encontró información relevante. "
            f"Fuentes consultadas: {', '.join(response.sources_tried) or 'ninguna'}."
        )

    citation_lines = "\n".join(
        f"  - {c.filename} — {c.section_title}"
        + (f" (pág. {c.page})" if c.page else "")
        for c in response.citations[:5]
    )
    return (
        f"[Bibliotecario — confianza: {response.confidence:.0%}]\n\n"
        f"{response.answer_text}\n\n"
        f"**Fuentes consultadas:** {', '.join(response.sources_tried)}\n"
        f"**Fuentes utilizadas:**\n{citation_lines}"
    )
