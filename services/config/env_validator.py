"""
services/config/env_validator.py — Fail-fast startup environment validation.

Call validate_env(module) as the FIRST executable line of every service before
any imports that open network or DB connections.

Design goals:
- Show ALL errors at once; never exit on the first error.
- Mask sensitive values in output — only log length, never content.
- Format validators: url, email, domain, int, bool, path.
- Group vars by subsystem so errors are easy to trace.

Usage::

    from services.config.env_validator import validate_env
    validate_env("kos")          # validates KOS + shared
    validate_env("llm")          # validates LLM + shared
    validate_env("mail")         # validates MAIL + shared
    validate_env("all")          # validates everything
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urlparse


# ── Validators ────────────────────────────────────────────────────────────────

def _is_url(value: str) -> bool:
    try:
        result = urlparse(value)
        return result.scheme in ("http", "https") and bool(result.netloc)
    except Exception:
        return False


def _is_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))


def _is_domain(value: str) -> bool:
    return bool(re.fullmatch(r"[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+", value))


def _is_int(value: str) -> bool:
    try:
        int(value)
        return True
    except ValueError:
        return False


def _is_bool(value: str) -> bool:
    return value.lower() in ("true", "false", "1", "0", "yes", "no")


def _is_path(value: str) -> bool:
    return bool(value)  # Any non-empty string is a valid path (existence not required)


FORMAT_VALIDATORS: dict[str, Callable[[str], bool]] = {
    "url":    _is_url,
    "email":  _is_email,
    "domain": _is_domain,
    "int":    _is_int,
    "bool":   _is_bool,
    "path":   _is_path,
}


# ── EnvVar descriptor ─────────────────────────────────────────────────────────

@dataclass
class EnvVar:
    name: str
    required: bool = True
    fmt: Optional[str] = None          # one of FORMAT_VALIDATORS keys
    description: str = ""
    min_length: int = 0
    sensitive: bool = False            # if True: log length only, never value


# ── Variable groups ───────────────────────────────────────────────────────────

KOS_VARS: list[EnvVar] = [
    EnvVar("KOS_DB_DSN",              required=True,  fmt="url",  description="PostgreSQL DSN"),
    EnvVar("KOS_REDIS_URL",           required=True,  fmt="url",  description="Redis URL for Celery"),
    EnvVar("KOS_KNOWLEDGE_STORE_ROOT",required=True,  fmt="path", description="Knowledge store root path"),
    EnvVar("KOS_CLAMD_HOST",          required=False,             description="ClamAV host"),
    EnvVar("KOS_CLAMD_PORT",          required=False, fmt="int",  description="ClamAV port"),
    EnvVar("KOS_GROBID_URL",          required=False, fmt="url",  description="GROBID URL for PDF metadata"),
    EnvVar("KOS_EMBEDDING_MODEL",     required=False,             description="Sentence-transformer model ID"),
    EnvVar("KOS_API_PORT",            required=False, fmt="int",  description="Librarian API port"),
]

LLM_VARS: list[EnvVar] = [
    EnvVar("OPENROUTER_API_KEY",  required=True,  sensitive=True, min_length=20,
           description="OpenRouter API key"),
    EnvVar("LLM_MODEL_HEAVY",    required=False,
           description="Model for heavy tasks (default: anthropic/claude-sonnet-4-5)"),
    EnvVar("LLM_MODEL_LIGHT",    required=False,
           description="Model for light tasks (default: openai/gpt-4o-mini)"),
    EnvVar("LLM_TIMEOUT_SECONDS",required=False, fmt="int",
           description="HTTP timeout for OpenRouter calls"),
]

LANGFUSE_VARS: list[EnvVar] = [
    EnvVar("LANGFUSE_HOST",        required=False, fmt="url",
           description="Self-hosted Langfuse URL (default: http://langfuse:3000)"),
    EnvVar("LANGFUSE_PUBLIC_KEY",  required=False, sensitive=True,
           description="Langfuse public key"),
    EnvVar("LANGFUSE_SECRET_KEY",  required=False, sensitive=True,
           description="Langfuse secret key"),
]

MAIL_VARS: list[EnvVar] = [
    EnvVar("MAIL_DOMAIN",                   required=True,  fmt="domain",
           description="Primary mail domain"),
    EnvVar("MAIL_SECRETARIO_ADDRESS",       required=True,  fmt="email",
           description="Secretary mailbox address"),
    EnvVar("MAIL_SECRETARIO_PASSWORD",      required=True,  sensitive=True, min_length=8,
           description="Secretary mailbox IMAP/SMTP password"),
    EnvVar("MAIL_SMTP_HOST",                required=False,
           description="SMTP relay host (default: postfix)"),
    EnvVar("MAIL_SMTP_PORT",                required=False, fmt="int",
           description="SMTP relay port (default: 587)"),
    EnvVar("MAIL_IMAP_HOST",                required=False,
           description="IMAP server host (default: dovecot)"),
    EnvVar("MAIL_IMAP_PORT",                required=False, fmt="int",
           description="IMAP server port (default: 993)"),
    EnvVar("MAIL_POLL_INTERVAL_SECONDS",    required=False, fmt="int",
           description="IMAP poll interval (default: 30)"),
    EnvVar("MAIL_RECEIVE_MODE",             required=False,
           description="'imap' or 'pipe' (default: imap)"),
    EnvVar("MAIL_REPORT_TIMEZONE",          required=False,
           description="Timezone for report schedules (default: America/Bogota)"),
    EnvVar("MAIL_MAX_DAILY_OUTBOUND",       required=False, fmt="int",
           description="Max outbound emails per day (default: 500)"),
    EnvVar("LIBRARIAN_API_URL",             required=False, fmt="url",
           description="Internal Librarian API URL (default: http://librarian_api:8001)"),
]

# All groups by module name
_VAR_GROUPS: dict[str, list[EnvVar]] = {
    "kos":      KOS_VARS,
    "llm":      LLM_VARS,
    "langfuse": LANGFUSE_VARS,
    "mail":     MAIL_VARS,
}


# ── Core validation logic ─────────────────────────────────────────────────────

def _validate_var(var: EnvVar) -> Optional[str]:
    """
    Validate a single EnvVar against os.environ.
    Returns an error string, or None if valid.
    """
    raw = os.environ.get(var.name)

    if raw is None or raw == "":
        if var.required:
            return f"  ✗ {var.name} — REQUIRED but not set. {var.description}"
        return None  # Optional and missing — OK

    # Minimum length check (useful for API keys)
    if var.min_length and len(raw) < var.min_length:
        masked = f"<{len(raw)} chars>"
        return (
            f"  ✗ {var.name} — value length insufficient "
            f"(got {masked}, need ≥{var.min_length} chars). {var.description}"
        )

    # Format check
    if var.fmt:
        validator = FORMAT_VALIDATORS.get(var.fmt)
        if validator and not validator(raw):
            display = f"<{len(raw)} chars>" if var.sensitive else repr(raw)
            return (
                f"  ✗ {var.name} — invalid {var.fmt} format "
                f"(got {display}). {var.description}"
            )

    return None


def validate_env(*modules: str) -> None:
    """
    Validate environment variables for one or more module groups.

    Args:
        *modules: One or more of: 'kos', 'llm', 'langfuse', 'mail', 'all'.
                  Pass no args to validate all.

    Exits with code 1 if ANY required variable is missing or invalid.
    Prints ALL errors before exiting — never stops at the first error.
    """
    if not modules or "all" in modules:
        groups_to_check = list(_VAR_GROUPS.keys())
    else:
        groups_to_check = list(modules)

    all_errors: list[str] = []

    for group in groups_to_check:
        vars_list = _VAR_GROUPS.get(group)
        if vars_list is None:
            # Unknown group — warn but don't crash
            print(
                f"[env_validator] WARNING: unknown module group '{group}' — skipping",
                file=sys.stderr,
            )
            continue

        group_errors: list[str] = []
        for var in vars_list:
            err = _validate_var(var)
            if err:
                group_errors.append(err)

        if group_errors:
            all_errors.append(f"\n[{group.upper()}]")
            all_errors.extend(group_errors)

    if all_errors:
        print("\n╔══════════════════════════════════════════════════════╗", file=sys.stderr)
        print("║  STARTUP ABORTED — environment configuration errors  ║", file=sys.stderr)
        print("╚══════════════════════════════════════════════════════╝", file=sys.stderr)
        for line in all_errors:
            print(line, file=sys.stderr)
        print(
            "\nFix the above variables in your .env file or Docker environment.\n",
            file=sys.stderr,
        )
        sys.exit(1)
