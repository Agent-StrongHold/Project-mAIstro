"""PM-fleet LLM-call adapter for the LLM gateway (LiteLLM-compatible).

This is the `llm_call: Callable[..., Awaitable[str]]` you pass into
`run_graph()` when running the PM persona DAG. It mirrors the same
`OpenAIChatModel + OpenAIProvider` pattern that conductor.py uses, but
exposes a flat HTTP call instead of going through pydantic-ai (the PM
DAG owns its own schema validation via PMRoleOutput, not pydantic-ai's
Agent[Out] machinery).

Reads at request time (process env, not bake-time):
  - `LITELLM_URL` (or `LITELLM_BASE_URL` as fallback) — LLM gateway URL
  - `LITELLM_MASTER_KEY` — per-developer MAISTRO virtual key
  - `DEFAULT_MODEL` (or call-time `model=`) — model alias (e.g. `claude-sonnet-4-6`)

JSON-mode is requested via `response_format={"type": "json_object"}`
when the call expects PMRoleOutput shape. Caller decides via the
`json_mode` kwarg.

Errors: HTTP errors raise `httpx.HTTPStatusError` (NodeRun's retry
machinery handles 429/5xx). Auth failures (401/403) bubble immediately.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

import httpx

from maistro.http import shared_client

logger = logging.getLogger(__name__)


def _resolve_base_url() -> str:
    # Support both the maistro-core naming convention (LITELLM_URL /
    # LITELLM_BASE_URL — what config/loader.py reads) and the MAISTRO
    # gateway's external naming (LITELLM_PROXY_URL — what .env ships
    # with). Either set works; the compose wires both.
    return (
        os.environ.get("LITELLM_URL")
        or os.environ.get("LITELLM_BASE_URL")
        or os.environ.get("LITELLM_PROXY_URL")
        or ""
    ).rstrip("/")


def _resolve_api_key() -> str:
    return os.environ.get("LITELLM_MASTER_KEY") or os.environ.get("LITELLM_PROXY_KEY") or ""


def _resolve_model(model: str | None) -> str:
    # Truthy-check, not key-presence: .env files often have `DEFAULT_MODEL=`
    # (key present, value empty), which `os.environ.get(k, default)` won't
    # fall back on. Sonnet 4.6 is the v0 default (confirmed available on
    # the LLM gateway).
    actual = model or os.environ.get("DEFAULT_MODEL") or "claude-sonnet-4-6"
    return actual.removeprefix("openai:")


async def maistro_llm_call(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float | None = None,
    json_mode: bool = True,
    timeout: float = 120.0,
    on_response: Callable[[dict[str, Any], httpx.Response], None] | None = None,
) -> str:
    """Call the LLM gateway with OpenAI-compatible chat-completions.

    Signature matches what `NodeRun.execute` invokes: positional
    `messages` + kwargs `model` + `temperature`. JSON mode is on by
    default since PM nodes always parse PMRoleOutput.

    `on_response`, if given, is invoked with the parsed body and the raw
    response right before `content` is returned — the seam quota recording
    (`maistro.quota.recorder`) hooks into, since this function otherwise
    discards `usage`/headers entirely once it extracts `content`. Optional
    and additive: omitting it changes nothing about existing callers. A
    failing hook is logged and swallowed — instrumentation on an already-
    successful call must never turn into a failure the caller has to handle.
    """
    base_url = _resolve_base_url()
    api_key = _resolve_api_key()
    if not base_url or not api_key:
        raise RuntimeError("LLM gateway not configured: LITELLM_URL + LITELLM_MASTER_KEY required.")

    body: dict[str, Any] = {
        "model": _resolve_model(model),
        "messages": messages,
    }
    if temperature is not None:
        body["temperature"] = temperature
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    async with shared_client(timeout=timeout) as client:
        resp = await client.post(
            f"{base_url}/v1/chat/completions",
            json=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        if resp.status_code >= 400:
            # Surface the gateway's error body so misconfigured calls
            # (unsupported response_format, bad model alias, etc.) are
            # debuggable from the logs rather than hidden behind httpx's
            # default short message.
            raise RuntimeError(f"LLM gateway {resp.status_code}: {resp.text[:1000]}")
        data = resp.json()
        content: str = data["choices"][0]["message"]["content"]
        if on_response is not None:
            try:
                on_response(data, resp)
            except Exception:
                logger.warning("on_response hook failed", exc_info=True)
        return content


__all__ = ["maistro_llm_call"]
