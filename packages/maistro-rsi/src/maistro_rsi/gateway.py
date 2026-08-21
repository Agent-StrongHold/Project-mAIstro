"""Gateway-backed ``llm_call`` for real benchmark evaluation.

`maistro_evolve`'s benchmark runners score a genome by calling an async
``llm_call(messages, *, temperature, max_tokens) -> str`` against a model — but
only when one is supplied. Given ``llm_call=None`` they fall back to a heuristic
(near-noise) score. `RsiCycle` used to pass nothing, so its "real benchmarks"
were never actually real. This module builds the missing callable: a thin async
client for the LiteLLM gateway (OpenAI-compatible ``/v1/chat/completions``), so
every provider the gateway exposes is reachable by model alias.

Kept dependency-free (httpx only, already a maistro-rsi dep) and reads the
gateway URL/key from the environment at call time, so it never bakes in config
and picks up whatever the caller has loaded (e.g. from the engine .env).
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

import httpx
import structlog

from maistro.http import shared_client

logger = structlog.get_logger()

# What the evolve benchmark runners expect: given a chat-message list (and
# optional sampling params), return the model's text response.
LlmCall = Callable[..., Awaitable[str]]


def _gateway_base() -> str:
    return (
        os.environ.get("LITELLM_URL")
        or os.environ.get("LITELLM_BASE_URL")
        or os.environ.get("LITELLM_PROXY_URL")
        or ""
    ).rstrip("/")


def _gateway_key() -> str:
    return os.environ.get("LITELLM_MASTER_KEY") or os.environ.get("LITELLM_PROXY_KEY") or ""


def make_gateway_llm_call(
    model: str,
    *,
    timeout: float = 60.0,
    on_response: Callable[[dict[str, object], httpx.Response], None] | None = None,
) -> LlmCall:
    """Return an async ``llm_call`` that routes to ``model`` via the gateway.

    The URL/key are resolved on each call (not captured here), so the callable
    keeps working if the environment is populated after it's constructed.

    `on_response`, if given, is invoked with the parsed body and the raw response
    right after the request succeeds — the same additive quota-recording seam
    `pm_llm_call.maistro_llm_call`/`conductor._call_gateway` expose, so RSI-cycle
    evaluation traffic can feed `maistro.quota.recorder` too. A failing hook is
    logged and swallowed since instrumentation on an already-successful call must
    never turn into a failure the caller has to handle.
    """

    async def llm_call(
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        base = _gateway_base()
        if not base:
            raise RuntimeError(
                "LiteLLM gateway not configured — set LITELLM_URL (+ LITELLM_MASTER_KEY). "
                "Benchmark scoring needs a live gateway to be real."
            )
        async with shared_client(timeout=timeout) as client:
            resp = await client.post(
                f"{base}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                headers={"Authorization": f"Bearer {_gateway_key()}"},
            )
            resp.raise_for_status()
            data = resp.json()
            if on_response is not None:
                try:
                    on_response(data, resp)
                except Exception:
                    await logger.awarning("rsi_gateway_on_response_hook_failed", exc_info=True)
            content = data["choices"][0]["message"].get("content") or ""

            # Reasoning models bill reasoning + output against the SAME budget,
            # so a tight max_tokens can leave zero visible output. Surface the
            # split (available in usage.completion_tokens_details) so that
            # failure is diagnosable — and feeds accurate reasoning-vs-output
            # cost into the latency/tokens signal — instead of a silent "".
            usage = data.get("usage") or {}
            # Cumulative counters exposed on the callable so callers (e.g.
            # RsiCycle → QuotaBurnScheduler.record_attempt) can close the
            # quota-burn feedback loop.
            llm_call.usage_input += int(usage.get("prompt_tokens") or 0)  # type: ignore[attr-defined]
            llm_call.usage_output += int(usage.get("completion_tokens") or 0)  # type: ignore[attr-defined]
            details = usage.get("completion_tokens_details") or {}
            reasoning = int(details.get("reasoning_tokens") or 0)
            completion = int(usage.get("completion_tokens") or 0)
            if reasoning and not content.strip():
                await logger.awarning(
                    "gateway_output_starved_by_reasoning",
                    model=model,
                    reasoning_tokens=reasoning,
                    completion_tokens=completion,
                    max_tokens=max_tokens,
                    hint="raise max_tokens or lower reasoning_effort",
                )
            elif reasoning:
                await logger.adebug(
                    "gateway_token_split",
                    model=model,
                    reasoning_tokens=reasoning,
                    output_tokens=completion - reasoning,
                )
            return content

    llm_call.usage_input = 0  # type: ignore[attr-defined]
    llm_call.usage_output = 0  # type: ignore[attr-defined]
    return llm_call
