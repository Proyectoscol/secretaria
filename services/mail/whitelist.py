"""
services/mail/whitelist.py — Domain whitelist enforcement.

ONLY emails from domains listed in mail_authorized_domains are processed.
Everything else is silently ignored — no bounce, no reply, no DB record.

Security design:
- No wildcards — 'proyectoscall.com' authorizes exactly that domain only.
- Empty whitelist = reject all (fail-safe).
- tenant_id is always required — no cross-tenant leakage.
"""

from __future__ import annotations

import logging
from typing import Optional

import psycopg2.extensions

log = logging.getLogger(__name__)


def is_authorized(
    from_domain: str,
    tenant_id: str,
    db_conn: psycopg2.extensions.connection,
) -> bool:
    """
    Return True only if from_domain is in the active whitelist for tenant_id.

    Args:
        from_domain: The sender's domain (e.g. 'proyectoscall.com').
        tenant_id:   The UUID of the tenant whose whitelist to check.
        db_conn:     An open psycopg2 connection.

    Returns:
        True if the domain is authorized, False otherwise.
    """
    if not from_domain or not tenant_id:
        return False

    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM mail_authorized_domains
                WHERE tenant_id = %s
                  AND domain    = %s
                  AND is_active = TRUE
                """,
                (tenant_id, from_domain.lower().strip()),
            )
            count = cur.fetchone()[0]
        authorized = count > 0
        if not authorized:
            log.info(
                "mail.whitelist: domain '%s' NOT authorized for tenant %s",
                from_domain,
                tenant_id,
            )
        return authorized
    except Exception:
        log.exception(
            "mail.whitelist: error checking domain '%s' for tenant %s",
            from_domain,
            tenant_id,
        )
        # Fail-safe: reject on any DB error
        return False


def get_tenant_for_recipient(
    to_address: str,
    db_conn: psycopg2.extensions.connection,
) -> Optional[str]:
    """
    Look up the tenant_id for an inbound email recipient.

    Given a destination address (e.g. 'secretaria@empresa.com'),
    find the matching active mail_account and return its tenant_id.

    Args:
        to_address: The full email address of the intended recipient.
        db_conn:    An open psycopg2 connection.

    Returns:
        tenant_id as a string UUID, or None if not found.
    """
    if not to_address or "@" not in to_address:
        return None

    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT tenant_id FROM mail_accounts
                WHERE email_address = %s AND is_active = TRUE
                LIMIT 1
                """,
                (to_address.lower().strip(),),
            )
            row = cur.fetchone()
        return str(row[0]) if row else None
    except Exception:
        log.exception(
            "mail.whitelist: error looking up tenant for recipient '%s'",
            to_address,
        )
        return None


def get_authorized_domains(
    tenant_id: str,
    db_conn: psycopg2.extensions.connection,
) -> list[str]:
    """Return all active authorized domains for a tenant (for display/logging)."""
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT domain FROM mail_authorized_domains
                WHERE tenant_id = %s AND is_active = TRUE
                ORDER BY domain
                """,
                (tenant_id,),
            )
            return [row[0] for row in cur.fetchall()]
    except Exception:
        log.exception("mail.whitelist: error listing domains for tenant %s", tenant_id)
        return []
