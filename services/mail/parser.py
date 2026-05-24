"""
services/mail/parser.py — RFC 5322 message parser.

Parses a raw email message (bytes) and returns a structured dict
that maps directly to the mail_messages table schema.

No external dependencies beyond the standard library.
"""

from __future__ import annotations

import email
import email.utils
import hashlib
import logging
from email.header import decode_header as _decode_header
from typing import Optional

log = logging.getLogger(__name__)


# ── Header decoding ───────────────────────────────────────────────────────────

def _decode(value: Optional[str]) -> str:
    """Decode an encoded email header value to a plain Unicode string."""
    if not value:
        return ""
    parts = _decode_header(value)
    result: list[str] = []
    for raw, charset in parts:
        if isinstance(raw, bytes):
            result.append(raw.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(raw)
    return " ".join(result).strip()


def _parse_address_list(msg: email.message.Message, header: str) -> list[dict]:
    """Parse a header containing one or more RFC 5322 addresses."""
    raw = _decode(msg.get(header, ""))
    return [
        {"name": name, "email": addr.lower()}
        for name, addr in email.utils.getaddresses([raw])
        if addr and "@" in addr
    ]


# ── Thread key ────────────────────────────────────────────────────────────────

def _compute_thread_key(message_id: str, in_reply_to: str, references: list[str]) -> str:
    """
    Compute a stable thread key from the chain of message IDs.

    Rules (in priority order):
    1. First message-ID in References is the thread root (oldest ancestor).
    2. If no References but has In-Reply-To: use In-Reply-To as root.
    3. If neither: this is a new thread; use own Message-ID as root.
    """
    root = references[0] if references else (in_reply_to or message_id)
    return hashlib.sha256(root.encode()).hexdigest()[:32]


# ── Body extraction ───────────────────────────────────────────────────────────

def _extract_body(msg: email.message.Message) -> tuple[str, str]:
    """Return (body_text, body_html) from a (possibly multipart) message."""
    body_text = ""
    body_html = ""

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = part.get_content_disposition() or ""
            if cd == "attachment":
                continue
            charset = part.get_content_charset() or "utf-8"
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            decoded = payload.decode(charset, errors="replace")
            if ct == "text/plain" and not body_text:
                body_text = decoded
            elif ct == "text/html" and not body_html:
                body_html = decoded
    else:
        ct = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if ct == "text/html":
                body_html = decoded
            else:
                body_text = decoded

    return body_text.strip(), body_html.strip()


# ── Attachment extraction ─────────────────────────────────────────────────────

def _extract_attachments(msg: email.message.Message) -> list[dict]:
    """Return a list of dicts, one per attachment found in the message."""
    attachments: list[dict] = []
    for part in msg.walk():
        disposition = part.get_content_disposition() or ""
        content_type = part.get_content_type()

        # Treat parts with Content-Disposition: attachment, or inline parts
        # that are not text/* and not multipart, as attachments.
        is_attachment = (
            disposition == "attachment"
            or (
                disposition == "inline"
                and not content_type.startswith("text/")
                and not content_type.startswith("multipart/")
            )
        )
        if not is_attachment:
            continue

        data = part.get_payload(decode=True)
        if data is None:
            continue

        filename = _decode(part.get_filename() or "") or "sin_nombre"

        attachments.append(
            {
                "filename": filename,
                "content_type": content_type,
                "data": data,
                "size_bytes": len(data),
            }
        )
    return attachments


# ── Spam / authentication headers ────────────────────────────────────────────

def _extract_spam_score(msg: email.message.Message) -> Optional[float]:
    """Parse Rspamd X-Spam-Score header if present."""
    score_header = msg.get("X-Spam-Score") or msg.get("X-Rspamd-Score")
    if score_header:
        try:
            return float(score_header.strip().split()[0])
        except (ValueError, IndexError):
            pass
    return None


def _extract_dkim_valid(msg: email.message.Message) -> Optional[bool]:
    """Parse Authentication-Results header for DKIM result."""
    auth = msg.get("Authentication-Results", "")
    if "dkim=pass" in auth.lower():
        return True
    if "dkim=fail" in auth.lower():
        return False
    return None


def _extract_spf_valid(msg: email.message.Message) -> Optional[bool]:
    """Parse Authentication-Results header for SPF result."""
    auth = msg.get("Authentication-Results", "")
    if "spf=pass" in auth.lower():
        return True
    if "spf=fail" in auth.lower() or "spf=softfail" in auth.lower():
        return False
    return None


# ── Main parser ───────────────────────────────────────────────────────────────

def parse_message(raw_email: bytes) -> dict:
    """
    Parse a raw RFC 5322 email message and return a structured dict.

    The returned dict maps directly to the mail_messages table schema.
    Attachments are returned as a separate list under the 'attachments' key.

    Args:
        raw_email: The raw email bytes as received from Postfix or IMAP.

    Returns:
        dict with all fields required by mail_messages, plus 'attachments'.
    """
    msg = email.message_from_bytes(raw_email)

    # ── From ──────────────────────────────────────────────────────────────────
    from_raw = _decode(msg.get("From", ""))
    from_name, from_address_raw = email.utils.parseaddr(from_raw)
    from_address = from_address_raw.lower().strip()
    from_domain = from_address.split("@")[1].lower() if "@" in from_address else ""

    # ── To / CC / BCC ─────────────────────────────────────────────────────────
    to_addresses = _parse_address_list(msg, "To")
    cc_addresses = _parse_address_list(msg, "Cc")
    bcc_addresses = _parse_address_list(msg, "Bcc")
    reply_to = _decode(msg.get("Reply-To", "")) or None

    # ── Message-ID / threading ────────────────────────────────────────────────
    message_id = msg.get("Message-ID", "").strip().strip("<>")
    if not message_id:
        # Synthesize a deterministic fallback ID
        message_id = f"generated-{hashlib.sha256(raw_email[:512]).hexdigest()[:16]}@kos"

    in_reply_to = msg.get("In-Reply-To", "").strip().strip("<>") or None
    references_raw = msg.get("References", "")
    references = [r.strip().strip("<>") for r in references_raw.split() if r.strip()]

    thread_key = _compute_thread_key(message_id, in_reply_to or "", references)

    # ── Date ──────────────────────────────────────────────────────────────────
    date_str = msg.get("Date")
    received_at = None
    if date_str:
        try:
            dt = email.utils.parsedate_to_datetime(date_str)
            received_at = dt.isoformat()
        except Exception:
            log.warning("Could not parse Date header: %r", date_str)

    # ── Body ──────────────────────────────────────────────────────────────────
    body_text, body_html = _extract_body(msg)

    # ── Subject ───────────────────────────────────────────────────────────────
    subject = _decode(msg.get("Subject", "")) or "(sin asunto)"

    # ── Attachments ───────────────────────────────────────────────────────────
    attachments = _extract_attachments(msg)

    # ── All raw headers ───────────────────────────────────────────────────────
    raw_headers = {k.lower(): str(v) for k, v in msg.items()}

    return {
        # Threading
        "message_id": message_id,
        "in_reply_to": in_reply_to,
        "references_list": references,
        "thread_key": thread_key,
        # Addresses
        "from_address": from_address,
        "from_name": from_name or None,
        "from_domain": from_domain,
        "to_addresses": to_addresses,
        "cc_addresses": cc_addresses,
        "bcc_addresses": bcc_addresses,
        "reply_to": reply_to,
        # Content
        "subject": subject,
        "body_text": body_text or None,
        "body_html": body_html or None,
        "snippet": (body_text or "")[:200] or None,
        # Technical metadata
        "received_at": received_at,
        "raw_headers": raw_headers,
        "spam_score": _extract_spam_score(msg),
        "dkim_valid": _extract_dkim_valid(msg),
        "spf_valid": _extract_spf_valid(msg),
        # Direction (always inbound when parsed by receiver)
        "direction": "inbound",
        # Attachments (separate list, not a DB column)
        "attachments": attachments,
    }
