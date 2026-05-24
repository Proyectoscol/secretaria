"""
services/mail/receiver.py — Inbound email receiver.

Two operating modes, selected by MAIL_RECEIVE_MODE:

  imap (default):
    Polls Dovecot via IMAP every MAIL_POLL_INTERVAL_SECONDS seconds.
    Reads UNSEEN messages, enqueues them for async processing via Celery,
    moves processed messages to 'Processed' folder.

  pipe:
    Reads a single message from stdin (invoked by Postfix pipe transport).
    Called once per incoming message. Enqueues via Celery and exits.

Both modes enqueue to services.mail.tasks.process_inbound_mail — the
actual parsing, whitelist check, and DB writes happen in the Celery worker.
"""

from __future__ import annotations

import imaplib
import logging
import os
import sys
import time

log = logging.getLogger(__name__)

IMAP_HOST = os.getenv("MAIL_IMAP_HOST", "dovecot")
IMAP_PORT = int(os.getenv("MAIL_IMAP_PORT", "993"))
IMAP_USER = os.getenv("MAIL_SECRETARIO_ADDRESS", "")
IMAP_PASS = os.getenv("MAIL_SECRETARIO_PASSWORD", "")
POLL_INTERVAL = int(os.getenv("MAIL_POLL_INTERVAL_SECONDS", "30"))
RECEIVE_MODE = os.getenv("MAIL_RECEIVE_MODE", "imap")


# ── IMAP polling ─────────────────────────────────────────────────────────────

def _ensure_folder(imap: imaplib.IMAP4_SSL, folder: str) -> None:
    """Create mailbox folder if it does not exist."""
    try:
        result = imap.select(f'"{folder}"')
        if result[0] == "NO":
            imap.create(f'"{folder}"')
    except imaplib.IMAP4.error:
        pass


def poll_inbox_once(imap: imaplib.IMAP4_SSL) -> int:
    """
    Process one pass over the INBOX.
    Returns the number of messages enqueued.
    """
    from services.mail.tasks import process_inbound_mail  # noqa: PLC0415

    imap.select("INBOX")
    _ensure_folder(imap, "Processed")
    _ensure_folder(imap, "Rejected")

    _, message_ids_raw = imap.search(None, "UNSEEN")
    message_ids = message_ids_raw[0].split() if message_ids_raw[0] else []

    enqueued = 0
    for msg_id in message_ids:
        try:
            _, msg_data = imap.fetch(msg_id, "(RFC822)")
            if not msg_data or msg_data[0] is None:
                continue

            raw_email: bytes = msg_data[0][1]

            # Enqueue async processing — the worker does parsing + DB writes
            process_inbound_mail.delay(raw_email, msg_id.decode())

            # Mark as read and move to Processed folder
            imap.store(msg_id, "+FLAGS", "\\Seen")
            imap.copy(msg_id, '"Processed"')
            imap.store(msg_id, "+FLAGS", "\\Deleted")

            enqueued += 1
            log.info("mail.receiver: enqueued message id=%s", msg_id.decode())

        except Exception:
            log.exception("mail.receiver: error processing IMAP message id=%s", msg_id)

    # Expunge deleted messages
    imap.expunge()
    return enqueued


def poll_loop() -> None:
    """
    Continuous IMAP polling loop.
    Called by the Celery Beat scheduler every POLL_INTERVAL seconds,
    or can be run as a standalone process.
    """
    if not IMAP_USER or not IMAP_PASS:
        log.error(
            "mail.receiver: MAIL_SECRETARIO_ADDRESS and MAIL_SECRETARIO_PASSWORD must be set"
        )
        return

    log.info(
        "mail.receiver: starting IMAP poll loop (%s@%s:%d, interval=%ds)",
        IMAP_USER,
        IMAP_HOST,
        IMAP_PORT,
        POLL_INTERVAL,
    )

    while True:
        try:
            with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as imap:
                imap.login(IMAP_USER, IMAP_PASS)
                count = poll_inbox_once(imap)
                if count:
                    log.info("mail.receiver: %d message(s) enqueued this pass", count)
        except imaplib.IMAP4.error as exc:
            log.error("mail.receiver: IMAP error: %s", exc)
        except OSError as exc:
            log.error("mail.receiver: connection error to %s:%d — %s", IMAP_HOST, IMAP_PORT, exc)
        except Exception:
            log.exception("mail.receiver: unexpected error in poll loop")

        time.sleep(POLL_INTERVAL)


# ── Postfix pipe mode ─────────────────────────────────────────────────────────

def pipe_receiver() -> None:
    """
    Read one email from stdin and enqueue it for processing.

    Called by Postfix when a message arrives (pipe transport).
    Must exit quickly — Postfix has a timeout for pipe delivery.
    """
    from services.mail.tasks import process_inbound_mail  # noqa: PLC0415

    raw_email = sys.stdin.buffer.read()
    if not raw_email:
        log.error("mail.receiver (pipe): received empty stdin")
        sys.exit(1)

    try:
        process_inbound_mail.delay(raw_email, None)
        log.info("mail.receiver (pipe): enqueued message (%d bytes)", len(raw_email))
        sys.exit(0)
    except Exception:
        log.exception("mail.receiver (pipe): failed to enqueue message")
        # Exit code 75 = EX_TEMPFAIL → Postfix will retry
        sys.exit(75)


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if RECEIVE_MODE == "pipe":
        pipe_receiver()
    else:
        poll_loop()
