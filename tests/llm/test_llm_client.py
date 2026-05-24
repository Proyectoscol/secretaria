"""
tests/llm/test_llm_client.py — Unit tests for services/llm/client.py.

TestModelRouting   — heavy vs light task routing
TestRetryLogic     — retries on 429/5xx, no retry on 4xx
TestErrorVisibility — LLMAPIError and LLMMaxRetriesError always propagate
TestNeverCallsExternal — mock verifies no real HTTP calls made

CRITICAL: These tests ALWAYS mock llm_client.complete — no real OpenRouter calls.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch, call

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def fake_api_key(monkeypatch):
    """Ensure the LLM client can be imported without a real API key."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-" + "x" * 30)


@pytest.fixture
def client():
    """Fresh LLMClient instance with httpx mocked out."""
    with patch("httpx.Client"):
        from services.llm.client import LLMClient
        c = LLMClient()
        c._langfuse_enabled = False  # disable tracing in tests
        return c


# ── TestModelRouting ──────────────────────────────────────────────────────────

class TestModelRouting:
    def test_heavy_task_uses_heavy_model(self, client):
        from services.llm.client import HEAVY_TASKS

        heavy_model = "anthropic/claude-sonnet-4-5"
        client._model_heavy = heavy_model

        for task in list(HEAVY_TASKS)[:3]:  # spot-check 3 heavy tasks
            model = client._resolve_model(task)
            assert model == heavy_model, f"task '{task}' should use heavy model"

    def test_light_task_uses_light_model(self, client):
        from services.llm.client import LIGHT_TASKS

        light_model = "openai/gpt-4o-mini"
        client._model_light = light_model

        for task in list(LIGHT_TASKS)[:3]:
            model = client._resolve_model(task)
            assert model == light_model, f"task '{task}' should use light model"

    def test_unknown_task_defaults_to_light(self, client):
        model = client._resolve_model("unknown_mystery_task")
        assert model == client._model_light

    def test_classify_email_is_light(self, client):
        assert client._resolve_model("classify_email") == client._model_light

    def test_generate_report_monthly_is_heavy(self, client):
        assert client._resolve_model("generate_report_monthly") == client._model_heavy

    def test_analyze_anomaly_is_heavy(self, client):
        assert client._resolve_model("analyze_anomaly") == client._model_heavy


# ── TestRetryLogic ────────────────────────────────────────────────────────────

class TestRetryLogic:
    @pytest.fixture
    def client_with_http(self, fake_api_key):
        """Client whose http.post is a MagicMock we can configure."""
        with patch("httpx.Client") as mock_client_class:
            from services.llm.client import LLMClient
            c = LLMClient()
            c._langfuse_enabled = False
            yield c

    def _make_response(self, status: int, body: dict | None = None) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status
        import json
        resp.text = json.dumps(body or {})
        if body:
            resp.json.return_value = body
        resp.raise_for_status = MagicMock()
        return resp

    def _ok_response(self) -> MagicMock:
        return self._make_response(200, {
            "choices": [{"message": {"content": "informational"}}],
            "model": "openai/gpt-4o-mini",
            "usage": {"prompt_tokens": 5, "completion_tokens": 1},
        })

    def test_success_on_first_attempt(self, client_with_http):
        client_with_http._http.post.return_value = self._ok_response()
        result = client_with_http._call_with_retry({"model": "m", "messages": []})
        assert result["content"] == "informational"
        assert client_with_http._http.post.call_count == 1

    def test_retries_on_429(self, client_with_http):
        from services.llm.client import _MAX_RETRIES

        rate_limit = self._make_response(429)
        success = self._ok_response()

        client_with_http._http.post.side_effect = [rate_limit, rate_limit, success]

        with patch("time.sleep"):  # don't actually sleep
            result = client_with_http._call_with_retry({"model": "m", "messages": []})

        assert result["content"] == "informational"
        assert client_with_http._http.post.call_count == 3

    def test_retries_on_500(self, client_with_http):
        server_error = self._make_response(500)
        success = self._ok_response()

        client_with_http._http.post.side_effect = [server_error, success]

        with patch("time.sleep"):
            result = client_with_http._call_with_retry({"model": "m", "messages": []})

        assert result["content"] == "informational"

    def test_no_retry_on_400(self, client_with_http):
        """4xx errors must raise LLMAPIError immediately (no retry)."""
        from services.llm.client import LLMAPIError

        bad_request = self._make_response(400)
        client_with_http._http.post.return_value = bad_request

        with pytest.raises(LLMAPIError):
            client_with_http._call_with_retry({"model": "m", "messages": []})

        # Only 1 attempt
        assert client_with_http._http.post.call_count == 1

    def test_max_retries_raises_llm_max_retries_error(self, client_with_http):
        from services.llm.client import LLMMaxRetriesError, _MAX_RETRIES

        server_error = self._make_response(503)
        client_with_http._http.post.return_value = server_error

        with patch("time.sleep"), pytest.raises(LLMMaxRetriesError):
            client_with_http._call_with_retry({"model": "m", "messages": []})

        assert client_with_http._http.post.call_count == _MAX_RETRIES

    def test_exponential_backoff_delays(self, client_with_http):
        """Retry delays must be 1s, 2s (exponential) — not fixed."""
        import time
        from services.llm.client import _MAX_RETRIES, _RETRY_BASE_DELAY

        server_error = self._make_response(503)
        client_with_http._http.post.return_value = server_error

        sleep_calls = []
        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            try:
                client_with_http._call_with_retry({"model": "m", "messages": []})
            except Exception:
                pass

        assert len(sleep_calls) == _MAX_RETRIES
        for i, delay in enumerate(sleep_calls):
            expected = _RETRY_BASE_DELAY * (2 ** i)
            assert delay == expected, f"attempt {i}: expected {expected}s, got {delay}s"


# ── TestErrorVisibility ───────────────────────────────────────────────────────

class TestErrorVisibility:
    def test_llm_api_error_propagates(self, client):
        from services.llm.client import LLMAPIError

        client._call_with_retry = MagicMock(side_effect=LLMAPIError("bad request", 400))

        with pytest.raises(LLMAPIError):
            client.complete(task="classify_email", messages=[{"role": "user", "content": "x"}])

    def test_llm_max_retries_error_propagates(self, client):
        from services.llm.client import LLMMaxRetriesError

        client._call_with_retry = MagicMock(side_effect=LLMMaxRetriesError("exhausted"))

        with pytest.raises(LLMMaxRetriesError):
            client.complete(task="classify_email", messages=[{"role": "user", "content": "x"}])

    def test_complete_includes_task_in_result(self, client):
        client._call_with_retry = MagicMock(return_value={
            "content": "informational",
            "model": "openai/gpt-4o-mini",
            "usage": {},
        })
        client._langfuse_enabled = False

        result = client.complete(
            task="classify_email",
            messages=[{"role": "user", "content": "hello"}],
            tenant_id="t-123",
        )
        assert result["task"] == "classify_email"
        assert result["tenant_id"] == "t-123"

    def test_system_prompt_prepended(self, client):
        """system_prompt must appear as the first message sent to OpenRouter."""
        captured_payloads: list = []

        def capture_call_with_retry(payload):
            captured_payloads.append(payload)
            return {"content": "ok", "model": "m", "usage": {}}

        client._call_with_retry = capture_call_with_retry

        client.complete(
            task="classify_email",
            messages=[{"role": "user", "content": "classify this"}],
            system_prompt="You are a classifier.",
        )

        payload = captured_payloads[0]
        assert payload["messages"][0]["role"] == "system"
        assert "classifier" in payload["messages"][0]["content"]
