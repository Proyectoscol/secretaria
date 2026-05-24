"""
MCP (Model Context Protocol) source connector — read-only.

The Librarian uses this to query structured external databases.
Credentials are never stored locally; they are resolved at call-time
from the vault reference in mcp_sources.credentials_vault_ref.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger(__name__)

# Keywords that signal a query is likely about structured/tabular data
_STRUCTURED_SIGNALS = re.compile(
    r"\b(cuántos?|cuántas?|cuales?|lista\s+de|total\s+de|factura|cliente|"
    r"inventario|pedido|producto|venta|precio|contrato|proveedor|"
    r"how\s+many|list\s+of|total\s+of|invoice|customer|inventory|order)\b",
    re.I,
)


@dataclass
class McpQueryResult:
    ok: bool
    source_name: str
    source_id: str
    data: Any = None                    # parsed JSON result
    result_summary: str = ""
    error: str = ""
    response_time_ms: int = 0


def query_implies_structured_data(query: str) -> bool:
    """Heuristic: does this query likely need a database lookup?"""
    return bool(_STRUCTURED_SIGNALS.search(query))


def find_relevant_source(
    query: str,
    tenant_id: str,
    db_conn,
) -> Optional[dict]:
    """
    Pick the most relevant active mcp_source for this query.

    Strategy: score each source's schema_snapshot and query_examples
    against the query using simple keyword overlap (no LLM).
    """
    sources = _list_active_sources(tenant_id, db_conn)
    if not sources:
        return None

    query_words = set(query.lower().split())
    best_source = None
    best_score = 0

    for source in sources:
        score = 0
        # Score from schema keywords
        schema = source.get("schema_snapshot") or {}
        schema_text = json.dumps(schema).lower()
        for word in query_words:
            if word in schema_text:
                score += 1

        # Score from query_examples
        examples = source.get("query_examples") or []
        examples_text = json.dumps(examples).lower()
        for word in query_words:
            if word in examples_text:
                score += 2  # examples carry more weight

        if score > best_score:
            best_score = score
            best_source = source

    return best_source if best_score > 0 else None


def execute_mcp_query(
    query: str,
    source: dict,
    tenant_id: str,
    requested_by: str,
    db_conn,
    vault_resolver=None,    # callable(vault_ref) → credentials dict; injected in prod
) -> McpQueryResult:
    """
    Send a read-only query to an MCP endpoint and return the result.

    ``query`` is a natural-language query; the MCP endpoint is expected to
    translate it internally (or we pass schema + query for it to handle).

    All executions are logged in mcp_query_log.
    """
    source_id = source["id"]
    source_name = source["name"]
    endpoint = source["mcp_endpoint"]

    # Resolve credentials from vault (never log them)
    credentials: dict = {}
    if vault_resolver:
        try:
            credentials = vault_resolver(source["credentials_vault_ref"])
        except Exception as exc:
            log.error("Vault resolution failed for source %s: %s", source_name, exc)
            return McpQueryResult(ok=False, source_name=source_name,
                                  source_id=source_id,
                                  error=f"Vault error: {exc}")

    payload = json.dumps({
        "query": query,
        "schema": source.get("schema_snapshot", {}),
        "read_only": True,          # signal to MCP endpoint
    }).encode()

    t0 = time.monotonic()
    try:
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                **{f"X-Credential-{k}": v for k, v in credentials.items()},
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            data = json.loads(raw)

        response_time_ms = int((time.monotonic() - t0) * 1000)
        result_summary = _summarize_result(data)

        _log_query(
            db_conn,
            source_id=source_id,
            tenant_id=tenant_id,
            query=query,
            result_summary=result_summary,
            requested_by=requested_by,
            response_time_ms=response_time_ms,
        )

        return McpQueryResult(
            ok=True,
            source_name=source_name,
            source_id=source_id,
            data=data,
            result_summary=result_summary,
            response_time_ms=response_time_ms,
        )

    except Exception as exc:
        response_time_ms = int((time.monotonic() - t0) * 1000)
        log.error("MCP query to %s failed: %s", endpoint, exc)
        _log_query(
            db_conn,
            source_id=source_id,
            tenant_id=tenant_id,
            query=query,
            result_summary="",
            requested_by=requested_by,
            response_time_ms=response_time_ms,
            error=str(exc),
        )
        return McpQueryResult(
            ok=False,
            source_name=source_name,
            source_id=source_id,
            error=str(exc),
            response_time_ms=response_time_ms,
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _list_active_sources(tenant_id: str, db_conn) -> list[dict]:
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, mcp_endpoint, schema_snapshot,
                       query_examples, credentials_vault_ref
                FROM mcp_sources
                WHERE tenant_id = %s AND is_active = TRUE
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()
    except Exception as exc:
        log.error("_list_active_sources error: %s", exc)
        return []

    return [
        {
            "id": str(r[0]),
            "name": r[1],
            "mcp_endpoint": r[2],
            "schema_snapshot": r[3],
            "query_examples": r[4],
            "credentials_vault_ref": r[5],
        }
        for r in rows
    ]


def _summarize_result(data: Any, max_len: int = 500) -> str:
    """Convert arbitrary JSON result to a short text summary."""
    if isinstance(data, list):
        return f"{len(data)} rows returned. First: {json.dumps(data[0])[:200]}" if data else "0 rows"
    if isinstance(data, dict):
        return json.dumps(data)[:max_len]
    return str(data)[:max_len]


def _log_query(
    db_conn,
    *,
    source_id: str,
    tenant_id: str,
    query: str,
    result_summary: str,
    requested_by: str,
    response_time_ms: int,
    error: str = "",
) -> None:
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mcp_query_log
                    (id, source_id, tenant_id, query_executed, result_summary,
                     requested_by, response_time_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid.uuid4()),
                    source_id,
                    tenant_id,
                    query,
                    result_summary or error,
                    requested_by,
                    response_time_ms,
                ),
            )
        db_conn.commit()
    except Exception as exc:
        log.warning("mcp_query_log insert error: %s", exc)
