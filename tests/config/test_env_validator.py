"""
tests/config/test_env_validator.py — Unit tests for env_validator.py.

Verifies:
  1. Missing required variable causes sys.exit(1).
  2. All errors shown at once (not just the first).
  3. Invalid URL format raises an error.
  4. Sensitive values are never logged (only length reported).
  5. Optional missing vars are silently accepted.
  6. Valid env passes without error.
"""

from __future__ import annotations

import os
import sys
from io import StringIO
from unittest.mock import patch

import pytest


def _run_validate(module: str, env: dict) -> tuple[int | None, str]:
    """
    Run validate_env(module) with a controlled environment.

    Returns (exit_code, stderr_output). exit_code is None if no SystemExit.
    """
    from services.config import env_validator  # import fresh each time

    stderr_capture = StringIO()

    with patch.dict(os.environ, env, clear=True), \
         patch("sys.stderr", stderr_capture):
        try:
            env_validator.validate_env(module)
            return None, stderr_capture.getvalue()
        except SystemExit as exc:
            return exc.code, stderr_capture.getvalue()


# ── 1. Missing required variable → exit 1 ────────────────────────────────────

class TestMissingRequired:
    def test_missing_kos_db_dsn_exits(self):
        env = {
            "KOS_REDIS_URL": "redis://localhost:6379/0",
            "KOS_KNOWLEDGE_STORE_ROOT": "/data/store",
        }
        code, _ = _run_validate("kos", env)
        assert code == 1

    def test_missing_openrouter_key_exits(self):
        env = {}
        code, _ = _run_validate("llm", env)
        assert code == 1

    def test_missing_mail_domain_exits(self):
        env = {
            "MAIL_SECRETARIO_ADDRESS": "bot@example.com",
            "MAIL_SECRETARIO_PASSWORD": "supersecretpass",
        }
        code, _ = _run_validate("mail", env)
        assert code == 1


# ── 2. All errors shown at once ───────────────────────────────────────────────

class TestAllErrorsAtOnce:
    def test_multiple_missing_vars_all_reported(self):
        """
        When KOS_DB_DSN, KOS_REDIS_URL, and KOS_KNOWLEDGE_STORE_ROOT are all
        missing, the error output must mention all three — not just the first.
        """
        code, stderr = _run_validate("kos", {})
        assert code == 1
        assert "KOS_DB_DSN" in stderr
        assert "KOS_REDIS_URL" in stderr
        assert "KOS_KNOWLEDGE_STORE_ROOT" in stderr

    def test_mail_multiple_errors(self):
        """Missing MAIL_DOMAIN + MAIL_SECRETARIO_ADDRESS + MAIL_SECRETARIO_PASSWORD."""
        code, stderr = _run_validate("mail", {})
        assert code == 1
        assert "MAIL_DOMAIN" in stderr
        assert "MAIL_SECRETARIO_ADDRESS" in stderr
        assert "MAIL_SECRETARIO_PASSWORD" in stderr


# ── 3. Format validation ──────────────────────────────────────────────────────

class TestFormatValidation:
    def test_invalid_db_url_exits(self):
        env = {
            "KOS_DB_DSN": "not-a-url",
            "KOS_REDIS_URL": "redis://localhost:6379/0",
            "KOS_KNOWLEDGE_STORE_ROOT": "/data",
        }
        code, stderr = _run_validate("kos", env)
        assert code == 1
        assert "KOS_DB_DSN" in stderr

    def test_invalid_redis_url_exits(self):
        env = {
            "KOS_DB_DSN": "postgresql://user:pass@db:5432/kos",
            "KOS_REDIS_URL": "not-redis",
            "KOS_KNOWLEDGE_STORE_ROOT": "/data",
        }
        code, stderr = _run_validate("kos", env)
        assert code == 1
        assert "KOS_REDIS_URL" in stderr

    def test_invalid_mail_domain_format(self):
        env = {
            "MAIL_DOMAIN": "not a domain!",
            "MAIL_SECRETARIO_ADDRESS": "bot@example.com",
            "MAIL_SECRETARIO_PASSWORD": "supersecretpassword1",
        }
        code, stderr = _run_validate("mail", env)
        assert code == 1
        assert "MAIL_DOMAIN" in stderr

    def test_invalid_email_address(self):
        env = {
            "MAIL_DOMAIN": "example.com",
            "MAIL_SECRETARIO_ADDRESS": "not-an-email",
            "MAIL_SECRETARIO_PASSWORD": "supersecretpassword1",
        }
        code, stderr = _run_validate("mail", env)
        assert code == 1
        assert "MAIL_SECRETARIO_ADDRESS" in stderr


# ── 4. Sensitive values never logged ─────────────────────────────────────────

class TestSensitiveValues:
    def test_api_key_value_not_in_output(self):
        """The actual API key must never appear in stderr, only its length."""
        secret = "sk-or-v1-supersecretapikey12345678"
        env = {
            "OPENROUTER_API_KEY": secret,
        }
        _, stderr = _run_validate("llm", env)
        assert secret not in stderr

    def test_api_key_too_brief_error_shows_length_not_value(self):
        """Brief API key should report length, not the value itself."""
        brief_key = "verybriefkey"
        env = {
            "OPENROUTER_API_KEY": brief_key,
        }
        code, stderr = _run_validate("llm", env)
        assert code == 1
        assert brief_key not in stderr
        # Should mention the length count
        assert str(len(brief_key)) in stderr

    def test_mail_password_not_in_output_when_too_brief(self):
        secret_pass = "abc"   # 3 chars — well under the 8-char minimum
        env = {
            "MAIL_DOMAIN": "example.com",
            "MAIL_SECRETARIO_ADDRESS": "bot@example.com",
            "MAIL_SECRETARIO_PASSWORD": secret_pass,
        }
        code, stderr = _run_validate("mail", env)
        assert code == 1
        assert secret_pass not in stderr


# ── 5. Optional vars silently accepted when missing ───────────────────────────

class TestOptionalVars:
    def test_optional_langfuse_vars_missing_ok(self):
        """Langfuse vars are all optional — missing them must not fail."""
        code, _ = _run_validate("langfuse", {})
        assert code is None  # no exit

    def test_optional_kos_vars_missing_ok(self):
        """
        KOS_CLAMD_HOST, KOS_GROBID_URL, KOS_EMBEDDING_MODEL are optional.
        Only the three required KOS vars matter.
        """
        env = {
            "KOS_DB_DSN": "postgresql://user:pass@db:5432/kos",
            "KOS_REDIS_URL": "redis://redis:6379/0",
            "KOS_KNOWLEDGE_STORE_ROOT": "/data/store",
            # KOS_CLAMD_HOST, KOS_GROBID_URL, KOS_EMBEDDING_MODEL intentionally absent
        }
        code, _ = _run_validate("kos", env)
        assert code is None


# ── 6. Valid env passes ───────────────────────────────────────────────────────

class TestValidEnv:
    def test_valid_kos_env_passes(self):
        env = {
            "KOS_DB_DSN": "postgresql://user:pass@db:5432/kos",
            "KOS_REDIS_URL": "redis://redis:6379/0",
            "KOS_KNOWLEDGE_STORE_ROOT": "/data/store",
        }
        code, _ = _run_validate("kos", env)
        assert code is None

    def test_valid_llm_env_passes(self):
        env = {
            "OPENROUTER_API_KEY": "sk-or-v1-" + "x" * 30,
        }
        code, _ = _run_validate("llm", env)
        assert code is None

    def test_valid_mail_env_passes(self):
        env = {
            "MAIL_DOMAIN": "empresa.com",
            "MAIL_SECRETARIO_ADDRESS": "secretaria@empresa.com",
            "MAIL_SECRETARIO_PASSWORD": "supersecretpassword1",
        }
        code, _ = _run_validate("mail", env)
        assert code is None

    def test_unknown_module_warns_but_does_not_exit(self, capsys):
        """Unknown module name should warn, not crash."""
        code, stderr = _run_validate("unknown_module", {})
        assert code is None
        assert "unknown_module" in stderr
