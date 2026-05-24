"""
services/llm/client.py — Unified LLM client via OpenRouter.

Rules enforced here:
- OpenRouter is the ONLY exit point for LLM calls. No direct calls to
  api.anthropic.com or api.openai.com.
- Langfuse traces all calls (self-hosted, TELEMETRY_ENABLED=false).
- Heavy tasks → LLM_MODEL_HEAVY (default: anthropic/claude-sonnet-4-5)
- Light tasks → LLM_MODEL_LIGHT  (default: openai/gpt-4o-mini)
- Embeddings are local with sentence-transformers — NOT wired here.
- Retry only for transient errors (timeout, 429, 5xx). Not for 4xx.
- All errors are visible; never except: pass.

Usage::

    from services.llm.client import llm_client

    result = llm_client.complete(
        task="classify_email",
        messages=[{"role": "user", "content": "..."}],
        tenant_id="t-123",
    )
    print(result["content"])   # the model's text response
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import httpx

log = logging.getLogger(__name__)

# ── Env validation — must complete before httpx client is constructed ─────────
# validate_env("llm") is called by the module-level singleton init below.
# Individual callers can also call it explicitly before importing this module.

# ── Model routing ─────────────────────────────────────────────────────────────
# Heavy tasks: large context, complex reasoning → Claude Sonnet
# Light tasks: short classification prompts → GPT-4o-mini

HEAVY_TASKS = frozenset({
    "generate_report_daily",
    "generate_report_weekly",
    "generate_report_monthly",
    "analyze_anomaly",
    "summarize_document",
    "answer_query",
})

LIGHT_TASKS = frozenset({
    "classify_email",
    "classify_chunk",
    "detect_language",
    "extract_keywords",
})

_DEFAULT_HEAVY = "anthropic/claude-sonnet-4-5"
_DEFAULT_LIGHT = "openai/gpt-4o-mini"

# ── Retry config ──────────────────────────────────────────────────────────────

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0        # seconds; doubles each retry
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


# ── Exceptions ────────────────────────────────────────────────────────────────

class LLMAPIError(Exception):
    """Non-retryable error from the LLM API (4xx, malformed response, etc.)."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class LLMMaxRetriesError(Exception):
    """Raised when all retry attempts are exhausted."""


# ── Client ────────────────────────────────────────────────────────────────────

class LLMClient:
    """
    Thin httpx wrapper for OpenRouter (OpenAI-compatible API).

    Thread-safe: httpx.Client uses a connection pool internally.
    All calls are synchronous — callers must be inside a Celery task.
    """

    def __init__(self) -> None:
        self._api_key: str = os.getenv("OPENROUTER_API_KEY", "")
        self._base_url: str = os.getenv(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        )
        self._timeout: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
        self._model_heavy: str = os.getenv("LLM_MODEL_HEAVY", _DEFAULT_HEAVY)
        self._model_light: str = os.getenv("LLM_MODEL_LIGHT", _DEFAULT_LIGHT)

        self._langfuse_enabled: bool = self._init_langfuse()

        self._http = httpx.Client(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "HTTP-Referer": "https://github.com/openclaw/openclaw",
                "X-Title": "KOS-Secretary",
            },
            timeout=self._timeout,
        )

        log.info(
            "llm.client: initialized (heavy=%s light=%s langfuse=%s)",
            self._model_heavy,
            self._model_light,
            self._langfuse_enabled,
        )

    def _init_langfuse(self) -> bool:
        """
        Try to initialise the Langfuse client.
        Returns True on success; False if Langfuse is not configured (non-fatal).
        """
        host = os.getenv("LANGFUSE_HOST", "")
        pub  = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        sec  = os.getenv("LANGFUSE_SECRET_KEY", "")

        if not (host and pub and sec):
            log.debug("llm.client: Langfuse not configured — tracing disabled")
            return False

        try:
            from langfuse import Langfuse  # type: ignore[import]

            self._langfuse = Langfuse(
                host=host,
                public_key=pub,
                secret_key=sec,
            )
            log.info("llm.client: Langfuse tracing enabled (host=%s)", host)
            return True
        except Exception as exc:
            log.warning("llm.client: Langfuse init failed — tracing disabled: %s", exc)
            return False

    # ── Model routing ─────────────────────────────────────────────────────────

    def _resolve_model(self, task: str) -> str:
        if task in HEAVY_TASKS:
            return self._model_heavy
        if task in LIGHT_TASKS:
            return self._model_light
        # Unknown task → light model + warning
        log.warning(
            "llm.client: unknown task '%s' — defaulting to light model %s",
            task,
            self._model_light,
        )
        return self._model_light

    # ── Core call ─────────────────────────────────────────────────────────────

    def complete(
        self,
        task: str,
        messages: list[dict],
        *,
        tenant_id: str = "",
        system_prompt: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> dict:
        """
        Send a chat completion request via OpenRouter.

        Args:
            task:          One of HEAVY_TASKS or LIGHT_TASKS — determines model.
            messages:      OpenAI-format message list.
            tenant_id:     Tenant UUID for Langfuse trace metadata.
            system_prompt: Optional system message prepended to `messages`.
            max_tokens:    Maximum tokens in response.
            temperature:   Sampling temperature (0.0 = deterministic).

        Returns:
            dict with keys: 'content' (str), 'model' (str), 'usage' (dict),
                            'task' (str), 'tenant_id' (str).

        Raises:
            LLMAPIError:        Non-retryable API or parsing error.
            LLMMaxRetriesError: Retried _MAX_RETRIES times without success.
        """
        model = self._resolve_model(task)

        full_messages: list[dict] = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        payload = {
            "model": model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        trace_id: Optional[str] = None
        if self._langfuse_enabled:
            trace_id = self._langfuse_start_trace(task, tenant_id, model, payload)

        result = self._call_with_retry(payload)
        result["task"] = task
        result["tenant_id"] = tenant_id

        if self._langfuse_enabled and trace_id:
            self._langfuse_end_trace(trace_id, result)

        return result

    # ── HTTP with retry ───────────────────────────────────────────────────────

    def _call_with_retry(self, payload: dict) -> dict:
        last_exc: Exception = RuntimeError("no attempts made")

        for attempt in range(_MAX_RETRIES):
            try:
                resp = self._http.post("/chat/completions", json=payload)

                # 4xx = non-retryable
                if 400 <= resp.status_code < 500:
                    raise LLMAPIError(
                        f"OpenRouter returned {resp.status_code}: {resp.text[:400]}",
                        status_code=resp.status_code,
                    )

                # 5xx / 429 = retryable
                if resp.status_code in _RETRYABLE_STATUS:
                    raise _RetryableError(
                        f"OpenRouter returned {resp.status_code}: {resp.text[:200]}"
                    )

                resp.raise_for_status()

                return self._parse_response(resp)

            except LLMAPIError:
                raise  # never retry

            except _RetryableError as exc:
                last_exc = exc

            except httpx.TimeoutException as exc:
                last_exc = exc
                log.warning(
                    "llm.client: timeout on attempt %d/%d for model %s",
                    attempt + 1,
                    _MAX_RETRIES,
                    payload.get("model"),
                )

            except httpx.RequestError as exc:
                # Network-level error — retryable
                last_exc = exc
                log.warning(
                    "llm.client: network error on attempt %d/%d: %s",
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                )

            # Exponential backoff: 1s → 2s → 4s
            delay = _RETRY_BASE_DELAY * (2 ** attempt)
            log.info(
                "llm.client: retrying in %.1fs (attempt %d/%d)",
                delay,
                attempt + 1,
                _MAX_RETRIES,
            )
            time.sleep(delay)

        raise LLMMaxRetriesError(
            f"LLM call failed after {_MAX_RETRIES} attempts. Last error: {last_exc}"
        ) from last_exc

    def _parse_response(self, resp: httpx.Response) -> dict:
        try:
            data = resp.json()
        except Exception as exc:
            raise LLMAPIError(
                f"Failed to parse OpenRouter JSON response: {exc}"
            ) from exc

        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
            model = data.get("model", "unknown")
            usage = data.get("usage", {})
        except (KeyError, IndexError) as exc:
            raise LLMAPIError(
                f"Unexpected OpenRouter response structure: {exc} — {str(data)[:300]}"
            ) from exc

        return {
            "content": content,
            "model": model,
            "usage": usage,
        }

    # ── Langfuse tracing ──────────────────────────────────────────────────────

    def _langfuse_start_trace(
        self, task: str, tenant_id: str, model: str, payload: dict
    ) -> Optional[str]:
        try:
            trace = self._langfuse.trace(
                name=f"llm_call:{task}",
                metadata={"tenant_id": tenant_id, "model": model},
                tags=[task, model],
            )
            trace.generation(
                name="openrouter_request",
                model=model,
                input=payload.get("messages", []),
                metadata={"tenant_id": tenant_id},
            )
            return trace.id
        except Exception as exc:
            log.debug("llm.client: Langfuse trace start failed: %s", exc)
            return None

    def _langfuse_end_trace(self, trace_id: str, result: dict) -> None:
        try:
            self._langfuse.trace(trace_id).update(
                output=result.get("content", ""),
                usage={
                    "input": result.get("usage", {}).get("prompt_tokens", 0),
                    "output": result.get("usage", {}).get("completion_tokens", 0),
                },
            )
        except Exception as exc:
            log.debug("llm.client: Langfuse trace end failed: %s", exc)

    def close(self) -> None:
        """Gracefully close the HTTP connection pool."""
        try:
            self._http.close()
        except Exception:
            pass
        if self._langfuse_enabled:
            try:
                self._langfuse.flush()
            except Exception:
                pass


class _RetryableError(Exception):
    """Internal sentinel — retryable HTTP error from OpenRouter."""


# ── Global singleton ──────────────────────────────────────────────────────────
# Instantiated at module import time. validate_env("llm") should be called
# before this module is imported so the API key is always present.

llm_client = LLMClient()
