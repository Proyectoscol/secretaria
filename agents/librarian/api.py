"""
Librarian REST API — internal endpoints for OpenClaw agents.

Runs as a standalone FastAPI service (port 8001 by default).
All endpoints are internal; they must NOT be exposed to the public internet.

Endpoints:
  POST /internal/librarian/query
  POST /internal/librarian/ingest
  GET  /internal/librarian/status/{job_id}
  POST /internal/librarian/onedrive/search
"""

from __future__ import annotations

# ── Env validation must be first — before any network/DB imports ──────────────
from services.config.env_validator import validate_env
validate_env("kos")

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import pathlib
import shutil

import psycopg2
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

log = logging.getLogger(__name__)

DB_DSN: str = os.getenv(
    "KOS_DB_DSN",
    "postgresql://openclaw:openclaw@postgres:5432/openclaw",
)


def _db():
    conn = psycopg2.connect(DB_DSN)
    try:
        from pgvector.psycopg2 import register_vector  # noqa: PLC0415
        register_vector(conn)
    except ImportError:
        pass
    return conn


# ── App ────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Librarian API starting on port %s", os.getenv("KOS_API_PORT", "8001"))
    yield
    log.info("Librarian API shutting down")


app = FastAPI(title="KOS Librarian", version="1.0.0", lifespan=lifespan)


# ── Request / Response models ──────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str
    tenant_id: str
    user_id: str
    session_id: str = ""
    context_hints: dict = {}
    microsoft_token: str = ""


class QueryResponse(BaseModel):
    citations: list[dict]   # renamed from "chunks" — matches frontend expectation
    sources_tried: list[str]
    sources_used: list[str]
    confidence: float
    answer_text: str
    from_cache: bool


class IngestRequest(BaseModel):
    file_path: str
    file_type: str
    source_type: str = "local_upload"
    tenant_id: str
    user_id: str
    session_id: str = ""
    source_id: Optional[str] = None


class IngestResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    document_id: Optional[str]
    error: Optional[str]


class OneDriveSearchRequest(BaseModel):
    query: str
    tenant_id: str
    user_id: str
    microsoft_token: str


class OneDriveSearchResponse(BaseModel):
    files_found: list[dict]
    indexed: list[str]
    requires_confirmation: list[str]


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.post("/internal/librarian/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    """
    Main query endpoint.  Delegates to router.route_query().
    Runs the synchronous router in a thread pool to avoid blocking.
    """
    from .router import route_query  # noqa: PLC0415

    db_conn = _db()
    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: asyncio.run(
                route_query(
                    query=req.query,
                    tenant_id=req.tenant_id,
                    user_id=req.user_id,
                    session_context={
                        "session_id": req.session_id,
                        **req.context_hints,
                    },
                    db_conn=db_conn,
                    microsoft_token=req.microsoft_token,
                )
            ),
        )
    except Exception as exc:
        log.exception("Query error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        db_conn.close()

    return QueryResponse(
        # Serialize Citation objects — document_id is now included in Citation dataclass
        citations=[
            {
                "filename": c.filename,
                "section_title": c.section_title,
                "page": c.page,
                "document_id": c.document_id,
                "score": c.score,
                "search_method": c.search_method,
            }
            for c in response.citations
        ],
        sources_tried=response.sources_tried,
        sources_used=response.sources_used,
        confidence=response.confidence,
        answer_text=response.answer_text,
        from_cache=response.from_cache,
    )


@app.post("/internal/librarian/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest):
    """Enqueue a document for ingestion via Celery."""
    from services.queue.tasks import process_document  # noqa: PLC0415

    db_conn = _db()
    job_id = str(uuid.uuid4())

    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_queue
                    (id, tenant_id, file_path, file_type, source_type,
                     requested_by_user_id, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'queued')
                """,
                (
                    job_id,
                    req.tenant_id,
                    req.file_path,
                    req.file_type,
                    req.source_type,
                    req.user_id,
                ),
            )
        db_conn.commit()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DB error: {exc}") from exc
    finally:
        # Single close in finally — avoids double-close when exception is raised
        db_conn.close()

    process_document.apply_async(
        kwargs={
            "file_path": req.file_path,
            "file_type": req.file_type,
            "tenant_id": req.tenant_id,
            "user_id": req.user_id,
            "source_type": req.source_type,
            "queue_job_id": job_id,
            "source_id": req.source_id,
            "session_id": req.session_id,
        }
    )

    return IngestResponse(job_id=job_id, status="queued")


@app.get("/internal/librarian/status/{job_id}", response_model=JobStatusResponse)
async def job_status(job_id: str):
    """Return current status of an ingestion job."""
    db_conn = _db()
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT iq.status, iq.error_detail, d.id
                FROM ingestion_queue iq
                LEFT JOIN documents d ON d.canonical_path LIKE '%' || iq.id || '%'
                WHERE iq.id = %s
                LIMIT 1
                """,
                (job_id,),
            )
            row = cur.fetchone()
    except Exception as exc:
        db_conn.close()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        db_conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(
        job_id=job_id,
        status=row[0],
        error=row[1],
        document_id=str(row[2]) if row[2] else None,
    )


@app.post("/internal/librarian/onedrive/search", response_model=OneDriveSearchResponse)
async def onedrive_search(req: OneDriveSearchRequest):
    """Search Graph API for files matching the query."""
    from .search_onedrive import search_graph_api  # noqa: PLC0415

    db_conn = _db()
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: search_graph_api(
                query=req.query,
                tenant_id=req.tenant_id,
                user_id=req.user_id,
                microsoft_token=req.microsoft_token,
                db_conn=db_conn,
            ),
        )
    except Exception as exc:
        log.exception("OneDrive search error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        db_conn.close()

    return OneDriveSearchResponse(
        files_found=result.files_found,
        indexed=result.indexed,
        requires_confirmation=result.requires_confirmation,
    )


@app.get("/internal/librarian/health")
async def health():
    return {"status": "ok"}


# ── File upload ────────────────────────────────────────────────────────────────

KNOWLEDGE_STORE_ROOT = os.getenv("KOS_KNOWLEDGE_STORE_ROOT", "/app/knowledge_store")
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".jpg", ".jpeg", ".png"}

MIME_TO_TYPE: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "image/jpeg": "image",
    "image/png": "image",
}


@app.post("/internal/upload")
async def upload_file(
    file: UploadFile = File(...),
    file_type: str = "",
    tenant_id: str = "",
    user_id: str = "",
    session_id: str = "",
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
    x_user_id: str = Header(default="", alias="X-User-ID"),
):
    """
    Receive a file upload from the Next.js proxy, persist it to the knowledge
    store staging area, then enqueue it for ingestion.

    tenant_id / user_id are injected by the proxy from the session headers
    (X-Tenant-ID / X-User-ID) — also accepted as form fields for fallback.
    """

    # Header values take precedence (injected by the proxy from server-side session);
    # form fields are a belt-and-suspenders fallback.
    effective_tenant_id = x_tenant_id or tenant_id
    effective_user_id = x_user_id or user_id

    if not effective_tenant_id:
        raise HTTPException(status_code=400, detail="Missing tenant_id / X-Tenant-ID")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    ext = pathlib.Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Extension '{ext}' not allowed")

    # Persist to a unique staging dir inside the knowledge store
    job_id = str(uuid.uuid4())
    staging_dir = pathlib.Path(KNOWLEDGE_STORE_ROOT) / "_upload_staging" / job_id
    staging_dir.mkdir(parents=True, exist_ok=True)
    dest = staging_dir / file.filename

    try:
        content = await file.read()
        dest.write_bytes(content)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not save file: {exc}") from exc

    # Derive file_type from extension if not provided
    resolved_type = file_type or ext.lstrip(".")

    # Enqueue via Celery
    db_conn = _db()
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_queue
                    (id, tenant_id, file_path, file_type, source_type,
                     requested_by_user_id, status)
                VALUES (%s, %s, %s, %s, 'local_upload', %s, 'queued')
                """,
                (job_id, effective_tenant_id, str(dest), resolved_type, effective_user_id),
            )
        db_conn.commit()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DB error: {exc}") from exc
    finally:
        db_conn.close()

    from services.queue.tasks import process_document  # noqa: PLC0415
    process_document.apply_async(
        kwargs={
            "file_path": str(dest),
            "file_type": resolved_type,
            "tenant_id": effective_tenant_id,
            "user_id": effective_user_id,
            "source_type": "local_upload",
            "queue_job_id": job_id,
            "session_id": session_id,
        }
    )

    return JSONResponse({"jobId": job_id, "status": "queued"})


# ── Library CRUD ───────────────────────────────────────────────────────────────

@app.get("/internal/library/documents")
async def list_documents(
    limit: int = 50,
    offset: int = 0,
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    """List processed documents for a tenant. tenant_id injected via X-Tenant-ID header."""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-ID header")
    db_conn = _db()
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    d.id,
                    d.tenant_id,
                    d.filename_original,
                    d.file_type,
                    d.file_size_bytes,
                    d.processing_status,
                    d.created_at,
                    d.processed_at,
                    COUNT(dc.id) AS chunk_count
                FROM documents d
                LEFT JOIN document_chunks dc ON dc.document_id = d.id
                WHERE d.tenant_id = %s
                GROUP BY d.id
                ORDER BY d.created_at DESC
                LIMIT %s OFFSET %s
                """,
                (x_tenant_id, limit, offset),
            )
            rows = cur.fetchall()
            cur.execute(
                "SELECT COUNT(*) FROM documents WHERE tenant_id = %s",
                (x_tenant_id,),
            )
            total = cur.fetchone()[0]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        db_conn.close()

    documents = [
        {
            "id": str(r[0]),
            "tenantId": r[1],
            "filename": r[2],
            "fileType": r[3],
            "fileSizeBytes": r[4],
            "processingStatus": r[5],
            "createdAt": r[6].isoformat() if r[6] else None,
            "processedAt": r[7].isoformat() if r[7] else None,
            "chunkCount": r[8],
        }
        for r in rows
    ]
    return {"documents": documents, "total": total}


@app.delete("/internal/library/documents/{document_id}")
async def delete_document(
    document_id: str,
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    """
    Delete a document and all its chunks/metadata.
    Tenant isolation: verifies the document belongs to tenant_id before deleting.
    """
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-ID header")
    db_conn = _db()
    try:
        with db_conn.cursor() as cur:
            # Verify ownership before delete
            cur.execute(
                "SELECT canonical_path FROM documents WHERE id = %s AND tenant_id = %s",
                (document_id, x_tenant_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Document not found")

            canonical_path = row[0]
            cur.execute(
                "DELETE FROM documents WHERE id = %s AND tenant_id = %s",
                (document_id, x_tenant_id),
            )
        db_conn.commit()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        db_conn.close()

    # Remove files from disk (non-fatal if already gone)
    if canonical_path:
        try:
            doc_dir = pathlib.Path(canonical_path).parent
            if doc_dir.exists():
                shutil.rmtree(str(doc_dir), ignore_errors=True)
        except Exception as exc:
            log.warning("Could not remove document files: %s", exc)

    return {"deleted": True}


@app.post("/internal/library/documents/{document_id}/reprocess")
async def reprocess_document(
    document_id: str,
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
    x_user_id: str = Header(default="", alias="X-User-ID"),
):
    """Re-enqueue a failed document for ingestion."""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-ID header")
    db_conn = _db()
    file_path: str = ""
    file_type: str = ""
    new_job_id: str = ""
    try:
        with db_conn.cursor() as cur:
            # Look up the most recent ingestion job for this document's tenant
            cur.execute(
                """
                SELECT iq.file_path, iq.file_type, iq.id
                FROM ingestion_queue iq
                WHERE iq.tenant_id = %s
                  AND EXISTS (
                    SELECT 1 FROM documents d
                    WHERE d.id = %s AND d.tenant_id = %s
                  )
                ORDER BY iq.created_at DESC
                LIMIT 1
                """,
                (x_tenant_id, document_id, x_tenant_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Document not found in queue")

            file_path, file_type = row[0], row[1]
            new_job_id = str(uuid.uuid4())

            cur.execute(
                """
                INSERT INTO ingestion_queue
                    (id, tenant_id, file_path, file_type, source_type,
                     requested_by_user_id, status)
                VALUES (%s, %s, %s, %s, 'reprocess', %s, 'queued')
                """,
                (new_job_id, x_tenant_id, file_path, file_type, x_user_id),
            )
            # Reset document status so it re-runs
            cur.execute(
                "UPDATE documents SET processing_status = 'pending' WHERE id = %s AND tenant_id = %s",
                (document_id, x_tenant_id),
            )
        db_conn.commit()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        db_conn.close()

    from services.queue.tasks import process_document  # noqa: PLC0415
    process_document.apply_async(
        kwargs={
            "file_path": file_path,
            "file_type": file_type,
            "tenant_id": x_tenant_id,
            "user_id": x_user_id,
            "source_type": "reprocess",
            "queue_job_id": new_job_id,
        }
    )

    return {"jobId": new_job_id, "status": "queued"}


# ── Entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn  # noqa: PLC0415

    uvicorn.run(
        "agents.librarian.api:app",
        host="0.0.0.0",
        port=int(os.getenv("KOS_API_PORT", "8001")),
        log_level="info",
    )
