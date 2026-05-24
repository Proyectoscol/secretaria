"""
Stage 0 — Security checks.

Every file MUST pass all checks before any processing occurs.
If any check fails, the file is quarantined and a SecurityResult with
``passed=False`` is returned.  Nothing downstream runs.

Zero LLM calls — only deterministic algorithms and OS tools.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import magic                            # python-magic (MIT)
import clamd                            # clamd (LGPLv2 — pure Python client)
import fitz                             # PyMuPDF (AGPL / commercial)

log = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
MAX_FILE_BYTES: int = int(os.getenv("KOS_MAX_FILE_BYTES", str(100 * 1024 * 1024)))  # 100 MB
CLAMD_SOCKET: str = os.getenv("KOS_CLAMD_SOCKET", "/var/run/clamav/clamd.sock")
CLAMD_HOST: str = os.getenv("KOS_CLAMD_HOST", "clamav")
CLAMD_PORT: int = int(os.getenv("KOS_CLAMD_PORT", "3310"))
QUARANTINE_ROOT: Path = Path(os.getenv("KOS_QUARANTINE_ROOT", "/app/quarantine"))

# Allowed (extension → MIME-type fragments).  If the real MIME doesn't contain
# any of the listed fragments the file is rejected.
ALLOWED_TYPES: dict[str, list[str]] = {
    ".pdf":  ["application/pdf"],
    ".docx": ["application/vnd.openxmlformats", "application/zip"],
    ".xlsx": ["application/vnd.openxmlformats", "application/zip"],
    ".pptx": ["application/vnd.openxmlformats", "application/zip"],
    ".html": ["text/html"],
    ".htm":  ["text/html"],
    ".jpg":  ["image/jpeg"],
    ".jpeg": ["image/jpeg"],
    ".png":  ["image/png"],
}

# Patterns that indicate prompt-injection attempts (heuristic, no LLM).
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.I),
    re.compile(r"\byou\s+are\s+now\b", re.I),
    re.compile(r"\bact\s+as\b", re.I),
    re.compile(r"\bpretend\s+you\s+are\b", re.I),
    re.compile(r"\bsystem\s+prompt\b", re.I),
    re.compile(r"\bforget\s+(?:all\s+)?(?:your\s+)?(?:previous\s+)?instructions", re.I),
    re.compile(r"<\s*!--.*?-->", re.S),            # HTML comments with hidden text
    re.compile(r"\[INST\]|\[SYS\]|<\|system\|>"),  # common prompt-template markers
]


@dataclass
class SecurityResult:
    passed: bool
    file_hash: Optional[str] = None
    duplicate_document_id: Optional[str] = None  # set when file already exists
    rejection_reason: Optional[str] = None
    scan_detail: dict = field(default_factory=dict)


# ── Public entry point ─────────────────────────────────────────────────────────

def run_security_checks(
    file_path: str,
    tenant_id: str,
    db_conn,            # psycopg2 / asyncpg connection — caller provides it
    *,
    skip_clamav: bool = False,  # for unit tests without ClamAV running
) -> SecurityResult:
    """
    Run all security checks.  Return ``SecurityResult`` — never raise.

    ``db_conn`` must expose a ``cursor()`` / ``execute()`` interface compatible
    with PEP-249 (psycopg2) or be an asyncpg connection used synchronously
    through a wrapper.
    """
    path = Path(file_path)

    # ── 0.1  SHA-256 deduplication ─────────────────────────────────────────────
    try:
        file_hash = _sha256(path)
    except OSError as exc:
        return SecurityResult(passed=False, rejection_reason=f"Cannot read file: {exc}")

    if db_conn is not None:
        existing_id = _check_existing_hash(db_conn, file_hash, tenant_id)
        if existing_id:
            log.info("Document already exists (hash=%s, id=%s) — skipping re-process",
                     file_hash[:12], existing_id)
            return SecurityResult(passed=True, file_hash=file_hash,
                                  duplicate_document_id=existing_id)

    # ── 0.2  MIME type validation ──────────────────────────────────────────────
    mime_result = _validate_mime(path)
    if not mime_result["ok"]:
        return _quarantine(path, tenant_id, file_hash,
                           mime_result["reason"],
                           {"mime_check": mime_result})

    # ── 0.3  File size limit ───────────────────────────────────────────────────
    size_bytes = path.stat().st_size
    if size_bytes > MAX_FILE_BYTES:
        return _quarantine(path, tenant_id, file_hash,
                           f"File too large: {size_bytes} bytes (max {MAX_FILE_BYTES})",
                           {"size_bytes": size_bytes})

    # ── 0.4  ClamAV antivirus scan ─────────────────────────────────────────────
    if not skip_clamav:
        av_result = _clamav_scan(path)
        if not av_result["ok"]:
            return _quarantine(path, tenant_id, file_hash,
                               f"Virus detected: {av_result.get('threat')}",
                               {"clamav": av_result})

    # ── 0.5  Macro detection (Office files only) ───────────────────────────────
    ext = path.suffix.lower()
    if ext in {".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt"}:
        macro_result = _check_macros(path)
        if not macro_result["ok"]:
            return _quarantine(path, tenant_id, file_hash,
                               f"Malicious macro detected: {macro_result.get('detail')}",
                               {"macro": macro_result})

    # ── 0.6  Prompt-injection heuristic ───────────────────────────────────────
    injection_result = _check_prompt_injection(path, ext)
    if not injection_result["ok"]:
        log.error(
            "Prompt injection pattern detected in %s (tenant=%s)",
            path.name, tenant_id
        )
        # Mark suspicious but quarantine; do NOT process.
        return _quarantine(path, tenant_id, file_hash,
                           "Prompt injection pattern detected",
                           {"injection": injection_result},
                           status="suspicious")

    return SecurityResult(
        passed=True,
        file_hash=file_hash,
        scan_detail={"size_bytes": size_bytes, "mime": mime_result},
    )


# ── Private helpers ────────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _check_existing_hash(db_conn, file_hash: str, tenant_id: str) -> Optional[str]:
    """Return document_id if this exact hash is already stored for this tenant."""
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM documents WHERE hash_sha256 = %s AND tenant_id = %s LIMIT 1",
                (file_hash, tenant_id),
            )
            row = cur.fetchone()
            return str(row[0]) if row else None
    except Exception as exc:  # noqa: BLE001
        log.warning("DB lookup for dedup failed: %s", exc)
        return None


def _validate_mime(path: Path) -> dict:
    ext = path.suffix.lower()
    if ext not in ALLOWED_TYPES:
        return {"ok": False, "reason": f"Extension '{ext}' not in allowlist"}

    try:
        real_mime = magic.from_file(str(path), mime=True)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"MIME detection error: {exc}"}

    allowed_fragments = ALLOWED_TYPES[ext]
    if not any(frag in real_mime for frag in allowed_fragments):
        return {
            "ok": False,
            "reason": (
                f"MIME mismatch: extension '{ext}' expects one of {allowed_fragments}, "
                f"got '{real_mime}'"
            ),
        }
    return {"ok": True, "real_mime": real_mime}


def _clamav_scan(path: Path) -> dict:
    """Scan with ClamAV via clamd socket or TCP fallback."""
    try:
        if Path(CLAMD_SOCKET).exists():
            cd = clamd.ClamdUnixSocket(path=CLAMD_SOCKET)
        else:
            cd = clamd.ClamdNetworkSocket(host=CLAMD_HOST, port=CLAMD_PORT)
        result = cd.scan(str(path))
        # result: {path: ('OK', None)} or {path: ('FOUND', 'Virus.Name')}
        status, threat = result.get(str(path), ("UNKNOWN", None))
        if status == "OK":
            return {"ok": True}
        return {"ok": False, "status": status, "threat": threat}
    except clamd.ConnectionError as exc:
        log.error("ClamAV unavailable: %s — file quarantined as precaution", exc)
        return {"ok": False, "status": "CLAMD_UNAVAILABLE", "threat": str(exc)}
    except Exception as exc:  # noqa: BLE001
        log.error("ClamAV scan error: %s", exc)
        return {"ok": False, "status": "ERROR", "threat": str(exc)}


def _check_macros(path: Path) -> dict:
    """Use oletools (olevba) to detect suspicious macros."""
    try:
        from oletools.olevba import VBA_Parser, TYPE_OLE, TYPE_OpenXML  # noqa: PLC0415

        vba = VBA_Parser(str(path))
        if not vba.detect_vba_macros():
            return {"ok": True, "has_macros": False}

        indicators = []
        for _, _, _, vba_code in vba.extract_macros():
            from oletools.olevba import detect_autoexec, detect_suspicious  # noqa: PLC0415
            indicators += [kw for kw, _ in detect_autoexec(vba_code)]
            indicators += [kw for kw, _ in detect_suspicious(vba_code)]

        if indicators:
            return {"ok": False, "has_macros": True,
                    "detail": f"Suspicious keywords: {indicators[:10]}"}
        # Macros present but no suspicious indicators
        return {"ok": True, "has_macros": True, "indicators": []}
    except ImportError:
        log.warning("oletools not installed — macro check skipped")
        return {"ok": True, "detail": "oletools not available"}
    except Exception as exc:  # noqa: BLE001
        log.error("Macro check error for %s: %s", path.name, exc)
        return {"ok": False, "detail": str(exc)}


def _check_prompt_injection(path: Path, ext: str) -> dict:
    """
    Heuristic prompt-injection detector.
    Only reads first ~500 words of plain text — no LLM involved.
    """
    raw_text = ""
    try:
        if ext == ".pdf":
            doc = fitz.open(str(path))
            words: list[str] = []
            for page in doc:
                words += page.get_text().split()
                if len(words) >= 500:
                    break
            raw_text = " ".join(words[:500])
            doc.close()
        elif ext in {".html", ".htm"}:
            from bs4 import BeautifulSoup  # noqa: PLC0415
            content = path.read_text(errors="replace")
            raw_text = BeautifulSoup(content, "html.parser").get_text()[:3000]
        else:
            # For Office files we do a shallow text read only
            raw_text = path.read_text(errors="replace")[:3000]
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not extract text for injection check: %s", exc)
        return {"ok": True, "note": "text extraction failed — pattern check skipped"}

    matches = []
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(raw_text):
            matches.append(pattern.pattern)

    if matches:
        return {"ok": False, "patterns_matched": matches}
    return {"ok": True}


def _quarantine(
    path: Path,
    tenant_id: str,
    file_hash: str,
    reason: str,
    detail: dict,
    *,
    status: str = "blocked",
) -> SecurityResult:
    """Move file to quarantine and return a failed SecurityResult."""
    dest_dir = QUARANTINE_ROOT / tenant_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    try:
        shutil.move(str(path), str(dest))
        log.error(
            "File quarantined: %s → %s  reason=%s  hash=%s",
            path.name, dest, reason, file_hash[:12],
        )
    except OSError as exc:
        log.error("Could not move file to quarantine: %s", exc)

    return SecurityResult(
        passed=False,
        file_hash=file_hash,
        rejection_reason=reason,
        scan_detail={"status": status, **detail},
    )
