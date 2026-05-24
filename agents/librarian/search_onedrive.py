"""
OneDrive search connector — on-demand, read-only.

Flow:
1. Check onedrive_index (already-seen files).
2. If file is known + content_cached → return summary/embedding.
3. If file is known but not cached → download, process in RAM, cache.
4. If file not in index → search Graph API, offer confirmation to user.

The Microsoft access token is passed per-request; it is NEVER persisted.
"""

from __future__ import annotations

import io
import json
import logging
import os
import tempfile
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
KNOWLEDGE_STORE_ROOT = Path(os.getenv("KOS_KNOWLEDGE_STORE_ROOT", "/app/knowledge_store"))
MAX_ONEDRIVE_FILE_BYTES = int(os.getenv("KOS_ONEDRIVE_MAX_FILE_BYTES",
                                        str(50 * 1024 * 1024)))  # 50 MB


@dataclass
class OneDriveSearchResult:
    files_found: list[dict]         # raw Graph items
    indexed: list[str]              # onedrive_file_ids already in our index
    requires_confirmation: list[str]  # new files needing user approval


@dataclass
class OneDriveContentResult:
    ok: bool
    content_text: str = ""
    summary_cache: str = ""
    onedrive_file_id: str = ""
    filename: str = ""
    error: str = ""


def search_onedrive_index(
    query: str,
    tenant_id: str,
    user_id: str,
    db_conn,
) -> list[dict]:
    """Search the local onedrive_index for files matching the query text."""
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, onedrive_file_id, filename, file_type, folder_path,
                       content_cached, summary_cache, document_id
                FROM onedrive_index
                WHERE tenant_id = %s AND user_id = %s
                  AND filename ILIKE %s
                LIMIT 20
                """,
                (tenant_id, user_id, f"%{query}%"),
            )
            rows = cur.fetchall()
    except Exception as exc:
        log.error("onedrive_index search error: %s", exc)
        return []

    return [
        {
            "id": str(r[0]),
            "onedrive_file_id": r[1],
            "filename": r[2],
            "file_type": r[3],
            "folder_path": r[4],
            "content_cached": r[5],
            "summary_cache": r[6],
            "document_id": str(r[7]) if r[7] else None,
        }
        for r in rows
    ]


def search_graph_api(
    query: str,
    tenant_id: str,
    user_id: str,
    microsoft_token: str,
    db_conn,
) -> OneDriveSearchResult:
    """
    Search Microsoft Graph API for files matching ``query``.
    Updates onedrive_index with newly discovered files (metadata only).
    """
    try:
        req = urllib.request.Request(
            f"{GRAPH_BASE}/me/drive/search(q='{urllib.parse.quote(query)}')"
            "?$select=id,name,fileSystemInfo,webUrl,parentReference,file"
            "&$top=20",
            headers={
                "Authorization": f"Bearer {microsoft_token}",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        log.error("Graph API search failed: %s", exc)
        return OneDriveSearchResult([], [], [])

    items = data.get("value", [])
    indexed: list[str] = []
    requires_confirmation: list[str] = []

    for item in items:
        file_id = item["id"]
        filename = item.get("name", "")
        file_info = item.get("file", {})
        mime = file_info.get("mimeType", "")

        # Only surfaces we can ingest
        if not _is_supported_mime(mime):
            continue

        # Check if already indexed
        already = _get_indexed(db_conn, file_id)
        if already:
            indexed.append(file_id)
        else:
            # Create metadata-only index entry (content_cached=False)
            _upsert_index_entry(
                db_conn, tenant_id=tenant_id, user_id=user_id, item=item
            )
            requires_confirmation.append(file_id)

    return OneDriveSearchResult(
        files_found=items,
        indexed=indexed,
        requires_confirmation=requires_confirmation,
    )


def fetch_and_process_onedrive_file(
    onedrive_file_id: str,
    tenant_id: str,
    user_id: str,
    microsoft_token: str,
    db_conn,
) -> OneDriveContentResult:
    """
    Download a OneDrive file, run it through the ingestion pipeline in RAM,
    and cache the result in onedrive_index.

    The file is written to a temp path then deleted after processing.
    """
    # Get file metadata from index
    row = _get_indexed(db_conn, onedrive_file_id)
    if not row:
        return OneDriveContentResult(ok=False, error="File not in onedrive_index")

    filename = row["filename"]
    file_type = (row["file_type"] or "").lstrip(".").lower() or "pdf"

    # Guard size
    size_bytes = row.get("size_bytes") or 0
    if size_bytes and size_bytes > MAX_ONEDRIVE_FILE_BYTES:
        return OneDriveContentResult(
            ok=False,
            error=f"File too large for on-demand processing ({size_bytes} bytes)",
        )

    # Download to temp file
    try:
        download_url = _get_download_url(onedrive_file_id, microsoft_token)
    except Exception as exc:
        return OneDriveContentResult(ok=False, error=f"Download URL failed: {exc}")

    tmp_path: Optional[Path] = None
    try:
        suffix = Path(filename).suffix or f".{file_type}"
        with tempfile.NamedTemporaryFile(
            suffix=suffix, dir="/tmp", delete=False
        ) as tmp:
            tmp_path = Path(tmp.name)

        req = urllib.request.Request(
            download_url,
            headers={"Authorization": f"Bearer {microsoft_token}"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            tmp_path.write_bytes(resp.read())

        # Run light ingestion (skip ClamAV for OneDrive files from trusted tenant)
        from services.ingestion.stage_1_extraction import extract_structure  # noqa: PLC0415

        extracted = extract_structure(str(tmp_path), file_type)
        summary = extracted.raw_text[:1000]

        # Generate embedding for summary
        from services.ingestion.stage_2_canonicalize import _get_encoder  # noqa: PLC0415
        encoder = _get_encoder()
        emb_vec = encoder.encode(summary, normalize_embeddings=True).tolist()

        # Update onedrive_index cache
        _update_cache(
            db_conn,
            onedrive_file_id=onedrive_file_id,
            tenant_id=tenant_id,
            summary=summary,
            embedding=emb_vec,
        )

        return OneDriveContentResult(
            ok=True,
            content_text=extracted.raw_text,
            summary_cache=summary,
            onedrive_file_id=onedrive_file_id,
            filename=filename,
        )

    except Exception as exc:
        log.error("OneDrive on-demand processing failed: %s", exc)
        return OneDriveContentResult(ok=False, error=str(exc))
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_indexed(db_conn, onedrive_file_id: str) -> Optional[dict]:
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT onedrive_file_id, filename, file_type, size_bytes,
                       content_cached, summary_cache, document_id
                FROM onedrive_index
                WHERE onedrive_file_id = %s
                LIMIT 1
                """,
                (onedrive_file_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "onedrive_file_id": row[0],
                "filename": row[1],
                "file_type": row[2],
                "size_bytes": row[3],
                "content_cached": row[4],
                "summary_cache": row[5],
                "document_id": str(row[6]) if row[6] else None,
            }
    except Exception as exc:
        log.error("_get_indexed error: %s", exc)
        return None


def _upsert_index_entry(db_conn, tenant_id: str, user_id: str, item: dict) -> None:
    try:
        parent = item.get("parentReference", {})
        fs = item.get("fileSystemInfo", {})
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO onedrive_index
                    (id, tenant_id, user_id, onedrive_file_id, filename, file_type,
                     size_bytes, last_modified_onedrive, weburl, folder_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (onedrive_file_id) DO UPDATE SET
                    last_checked_at = NOW(),
                    filename = EXCLUDED.filename
                """,
                (
                    str(uuid.uuid4()),
                    tenant_id,
                    user_id,
                    item["id"],
                    item.get("name"),
                    _mime_to_ext(item.get("file", {}).get("mimeType", "")),
                    item.get("size"),
                    fs.get("lastModifiedDateTime"),
                    item.get("webUrl"),
                    parent.get("path"),
                ),
            )
        db_conn.commit()
    except Exception as exc:
        log.error("_upsert_index_entry error: %s", exc)


def _update_cache(
    db_conn,
    onedrive_file_id: str,
    tenant_id: str,
    summary: str,
    embedding: list,
) -> None:
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                UPDATE onedrive_index
                SET content_cached = TRUE,
                    summary_cache = %s,
                    embedding_cache = %s::vector,
                    last_checked_at = NOW()
                WHERE onedrive_file_id = %s AND tenant_id = %s
                """,
                (summary, embedding, onedrive_file_id, tenant_id),
            )
        db_conn.commit()
    except Exception as exc:
        log.error("_update_cache error: %s", exc)


def _get_download_url(file_id: str, token: str) -> str:
    req = urllib.request.Request(
        f"{GRAPH_BASE}/me/drive/items/{file_id}?$select=@microsoft.graph.downloadUrl",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    return data["@microsoft.graph.downloadUrl"]


def _is_supported_mime(mime: str) -> bool:
    supported = [
        "application/pdf",
        "application/vnd.openxmlformats",
        "application/vnd.ms-excel",
        "text/html",
        "image/jpeg",
        "image/png",
    ]
    return any(mime.startswith(s) for s in supported)


def _mime_to_ext(mime: str) -> str:
    mapping = {
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml": "docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml": "xlsx",
        "application/vnd.openxmlformats-officedocument.presentationml": "pptx",
        "text/html": "html",
        "image/jpeg": "jpg",
        "image/png": "png",
    }
    for prefix, ext in mapping.items():
        if mime.startswith(prefix):
            return ext
    return "bin"


# Fix missing import
import urllib.parse  # noqa: E402
