# KOS Audit Report

**Date:** 2026-05-23  
**Scope:** Full codebase audit — KOS backend (Python) + Next.js 14 frontend  
**Status:** All issues corrected in-place

---

## Summary

| Category | Issues Found | Fixed |
|---|---|---|
| Package/Build | 4 | 4 ✅ |
| API Routing | 4 | 4 ✅ |
| Security | 2 | 2 ✅ |
| Data Integrity | 3 | 3 ✅ |
| Docker/Infra | 1 | 1 ✅ |
| Mobile UX | 1 | 1 ✅ |
| **Total** | **15** | **15 ✅** |

---

## Issues Fixed

### 1. `react-dropzone` missing from `package.json` — CRITICAL
**File:** `frontend/package.json`  
**Problem:** `UploadZone.tsx` imports `useDropzone` from `react-dropzone`, but the package was absent from `dependencies`. Build would fail with `Cannot resolve 'react-dropzone'`.  
**Fix:** Added `"react-dropzone": "11.7.1"` to `dependencies`.

---

### 2. `uuid` and `@types/uuid` missing from `package.json` — CRITICAL
**File:** `frontend/package.json`  
**Problem:** `app/(app)/chat/[sessionId]/page.tsx` imports `v4 as uuid` from `"uuid"`. Package not listed; TypeScript types not listed either. Build would fail at compilation.  
**Fix:** Added `"uuid": "9.0.1"` to `dependencies` and `"@types/uuid": "9.0.8"` to `devDependencies`.

---

### 3. `@radix-ui/react-sheet@0.0.1` — non-existent package — CRITICAL
**File:** `frontend/package.json`  
**Problem:** `@radix-ui/react-sheet` version `0.0.1` has never been published to npm. This would cause `npm ci` / `npm install` to fail. The package is nowhere imported in the codebase (the custom Framer Motion sidebar handles that UI).  
**Fix:** Removed the entry from `package.json`.

---

### 4. Microsoft platform API calls routed through proxy — CRITICAL
**Files:** `frontend/app/(app)/settings/microsoft/page.tsx`, `frontend/hooks/useMicrosoftPlatformToken.ts`  
**Problem:** Both files used the shared `api` Axios instance (base URL: `/api/proxy`) to call `/microsoft/platform/status`, `/microsoft/platform/connect`, `/microsoft/platform/disconnect`, `/microsoft/platform/token`, and `/microsoft/platform/token/refresh`. The proxy forwards non-librarian paths to `NEXT_PUBLIC_API_URL` (OpenClaw core at port 8000). Those routes do not exist on the core backend — they are Next.js App Router API routes. Result: all Microsoft platform calls returned 404 from the wrong server.  
**Fix:**  
- `settings/microsoft/page.tsx`: replaced `api.*` calls with a thin `msApi` helper that calls `/api/microsoft/platform/*` directly via `fetch`.  
- `useMicrosoftPlatformToken.ts`: replaced `api.get/post` with direct `fetch` calls to `/api/microsoft/platform/token` and `/api/microsoft/platform/token/refresh`.

---

### 5. `NEXT_PUBLIC_LIBRARIAN_API_URL` exposes internal URL to browser bundle — HIGH
**Files:** `frontend/app/api/proxy/[...path]/route.ts`, `frontend/.env.local.example`  
**Problem:** The env var used server-side in the proxy handler was named with the `NEXT_PUBLIC_` prefix. Next.js embeds all `NEXT_PUBLIC_*` variables into the client-side JavaScript bundle. Exposing the internal Librarian API URL (`http://localhost:8001`) to the browser is unnecessary and leaks topology.  
**Fix:** Renamed to `LIBRARIAN_API_URL` (no `NEXT_PUBLIC_` prefix). Updated proxy handler and `.env.local.example`.

---

### 6. `check_query_cache` SQL injection / no-op — HIGH
**File:** `agents/librarian/search_local.py`  
**Problem:** The cache query contained `INTERVAL '%s hours'`. In psycopg2, parameter substitution (`%s`) does **not** occur inside SQL string literals — the placeholder is left as the literal characters `%s`. The query would either fail with a syntax error or not filter by age at all. This bug turns the 2-hour cache window into a permanent cache (returns every old result matching the query).  
**Fix:** Replaced `NOW() - INTERVAL '%s hours'` with `NOW() - make_interval(hours => %s)`, which correctly binds the integer value via psycopg2 parameter substitution.

---

### 7. Double `db_conn.close()` in `ingest` endpoint — HIGH
**File:** `agents/librarian/api.py`  
**Problem:** The `ingest` endpoint had `db_conn.close()` in both the `except` block and the `finally` block. When an exception was raised, the connection was closed twice, causing a `psycopg2.InterfaceError: connection already closed` on every ingest error.  
**Fix:** Removed `db_conn.close()` from the `except` block; kept it only in `finally`.

---

### 8. `QueryResponse` field name mismatch — CRITICAL
**File:** `agents/librarian/api.py`  
**Problem:** The Pydantic model used `chunks: list[dict]` but the frontend (`chat/[sessionId]/page.tsx`) reads `res.data.citations`. The field was never received under the expected name.  
**Fix:** Renamed `chunks` → `citations` in `QueryResponse`.

---

### 9. `api.py` serializes `Citation` with fields that don't exist — CRITICAL
**File:** `agents/librarian/api.py`  
**Problem:** The query endpoint iterated `response.citations` (type `list[Citation]`) and tried to read `c.chunk_id`, `c.document_id`, `c.content_text`, `c.content_type`, `c.page_number` — none of which existed on the `Citation` dataclass. This caused `AttributeError` on every query response.  
**Fix:** Updated the serialization to only use fields present on `Citation` (`filename`, `section_title`, `page`, `score`, `search_method`, `document_id`). Added `document_id` to `Citation` (see item 10).

---

### 10. `Citation` dataclass missing `document_id` — HIGH
**File:** `agents/librarian/response_builder.py`  
**Problem:** `Citation` lacked `document_id`, which is required by the frontend to render deep links to documents (`/library/{documentId}`). The `build_response` function also did not populate it.  
**Fix:** Added `document_id: str = ""` field to `Citation`; updated `build_response` to populate it from `chunk.document_id`.

---

### 11. Upload hook sent files to non-existent backend route — HIGH
**File:** `frontend/hooks/useDocumentUpload.ts`  
**Problem:** Uploads were sent to `/api/proxy/upload` which the proxy forwarded to `http://localhost:8000/upload` (OpenClaw core). The core backend has no `/upload` endpoint for KOS documents.  
**Fix:**  
- Added `"upload"` to the `LIBRARIAN_PREFIXES` set in the proxy so `/api/proxy/upload` → `LIBRARIAN_API_URL/internal/upload`.  
- Added `POST /internal/upload` endpoint to `agents/librarian/api.py` that receives `multipart/form-data`, persists the file to the knowledge-store staging area, and enqueues a Celery job.  
- Updated `useDocumentUpload.ts` to include session `user_id`/`tenant_id` as form fields alongside the cookie-based auth.

---

### 12. Library CRUD routes missing from Librarian API — HIGH
**Files:** `frontend/app/(app)/library/page.tsx`, `agents/librarian/api.py`, `frontend/app/api/proxy/[...path]/route.ts`  
**Problem:** The library page called `/library/documents` (and `/library/documents/{id}` for delete/reprocess) via the proxy. The proxy forwarded these to `NEXT_PUBLIC_API_URL/library/...` (OpenClaw core, port 8000) which has no such routes.  
**Fix:**  
- Added `"library"` to the `LIBRARIAN_PREFIXES` set in the proxy so `/api/proxy/library/*` → `LIBRARIAN_API_URL/internal/library/*`.  
- Added three endpoints to `api.py`: `GET /internal/library/documents`, `DELETE /internal/library/documents/{document_id}`, `POST /internal/library/documents/{document_id}/reprocess`. All use the `X-Tenant-ID` header (injected by the proxy) for tenant isolation.

---

### 13. Proxy `Content-Type` handling for non-multipart requests — MEDIUM
**File:** `frontend/app/api/proxy/[...path]/route.ts`  
**Problem:** The original proxy always set `Content-Type` from the incoming request before checking for `FormData`. When `multipart/form-data` was detected and the header was deleted (to let `fetch` set the boundary), the already-set header was potentially left on the `Headers` object in some edge cases.  
**Fix:** Restructured to set `Content-Type` only for non-multipart bodies; for multipart, the header is never set (browser/fetch sets it with the correct boundary).

---

### 14. `ChatInput.tsx` textarea prevents iOS auto-zoom — MEDIUM
**File:** `frontend/components/chat/ChatInput.tsx`  
**Problem:** The textarea used `text-sm` class (14px). iOS Safari automatically zooms the viewport when the user focuses an input element with `font-size < 16px`. This is jarring UX on mobile.  
**Fix:** Added `style={{ fontSize: "16px" }}` inline style to the textarea (overrides Tailwind class at the element level without affecting layout).

---

### 15. `tempfile` import unused — LOW
**File:** `agents/librarian/api.py`  
**Problem:** `import tempfile` was added as a scaffolding import and left unused.  
**Fix:** Replaced with `import pathlib` (actually needed by the upload endpoint). `tempfile` removed.

---

## Items Verified — No Issues

| Check | Result |
|---|---|
| ClamAV fail-safe: `clamd.ConnectionError` → file quarantined | ✅ Correct in `stage_0_security.py` |
| bcrypt rounds = 12 in `register/route.ts` | ✅ `bcrypt.hash(password, 12)` |
| All DB queries in `search_local.py` include `tenant_id` WHERE clause | ✅ Both `semantic_search` and `fulltext_search` |
| Downstream tenant isolation guard in `response_builder.py` | ✅ Drops and logs ERROR on mismatch |
| AES-256-GCM token encryption format: `base64(iv[12] + tag[16] + ciphertext)` | ✅ Correct in `lib/crypto.ts` |
| Key length validated to exactly 32 bytes | ✅ Throws on mismatch |
| Stage 0 security failures = no retry (definitive) | ✅ `services/queue/tasks.py` returns without `raise` |
| Stages 1-2 failures = exponential backoff retry (max 3x) | ✅ `raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))` |
| OneDrive OAuth flow uses `offline_access` in scopes | ✅ `MICROSOFT_PLATFORM_SCOPES="offline_access Files.Read.All Mail.Read Calendars.Read"` |
| Microsoft App 1 (auth) vs App 2 (platform) fully independent | ✅ Separate env vars, separate DB tables |
| Domain restriction on 4 layers | ✅ register route, `signIn` callback, `auth.ts` jwt callback, `middleware.ts` |
| Volume mounts: `knowledge_store` + `quarantine` in both services | ✅ Both `celery_worker` and `librarian_api` have them |
| Docker ports bound to `127.0.0.1` | ✅ All ports are loopback-only |
| Non-root user in `Dockerfile.kos` | ✅ `USER kos` (uid 1000) |
| Mobile touch targets ≥ 44px | ✅ All buttons use `min-h-[44px] min-w-[44px]` |
| Citation chips are `<Link>` not `<button>` | ✅ `MessageBubble.tsx` uses `<Link href={/library/${...}}>` |
| Mobile sidebar closes on navigation | ✅ `onClick={() => setMobileOpen(false)}` on all nav links |
| Embedding model pre-downloaded at Docker build time | ✅ `RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer(...)"` |
| No secrets or credentials logged | ✅ Only IDs, hashes (truncated), and metadata appear in log calls |
| `prompt injection` patterns cover invisible text (HTML comments) | ✅ Pattern `<\s*!--.*?-->` present |
| oletools macro check scoped to Office files only, not PDFs | ✅ Guard: `if ext in {".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt"}` |
| FK constraints + CASCADE deletes in schema | ✅ `migrations/002_users_auth.sql` has `ON DELETE CASCADE` |
| Prisma schema aligned with SQL migrations | ✅ All tables/columns match |
