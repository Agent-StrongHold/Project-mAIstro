"""LiteLLM-gateway callable for the builders agent loop.

Reads at call time (never baked in):
  - LITELLM_URL / LITELLM_BASE_URL / LITELLM_PROXY_URL — gateway base URL
  - LITELLM_MASTER_KEY / LITELLM_PROXY_KEY /
    LITELLM_API_KEY / LITELLM_VIRTUAL_KEY              — bearer key
  - MAISTRO_BUILDERS_MODEL / DEFAULT_MODEL             — default model alias

The gateway exposes an OpenAI-compatible /v1/chat/completions endpoint, so
every LiteLLM-supported provider (Anthropic, OpenAI, Groq, Mistral, Ollama,
Azure, Bedrock, …) is reachable by changing the model alias.

`maistro builders` runs on the bare host (a `uv tool install`, not a
container), so none of the above are set by default — they only live in the
engine checkout's .env, used by docker-compose. `_ensure_env_loaded()` fills
that gap once per process: find the engine root (MAISTRO_REPO_ROOT env var,
then an upward walk from CWD), load its .env for any of the above keys that
aren't already real env vars, and rewrite the Docker-internal `litellm`
hostname to 127.0.0.1 since that's not reachable from the host. Already-set
env vars are never overridden — this only fills gaps.

Falls back to a stub response when the gateway is not configured so the TUI
can still start in dev mode without a running proxy.
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_ENV_KEYS = (
    "LITELLM_URL",
    "LITELLM_BASE_URL",
    "LITELLM_PROXY_URL",
    "LITELLM_MASTER_KEY",
    "LITELLM_PROXY_KEY",
    "MAISTRO_BUILDERS_MODEL",
    "DEFAULT_MODEL",
)

_env_loaded = False


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
    return values


def _ensure_env_loaded() -> None:
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True

    # Never reach outside the test process during a test run — tests rely on
    # "no env vars set" meaning "gateway not configured" (stub response), and
    # silently picking up a real .env from a nearby engine-root checkout would
    # break that isolation. PYTEST_CURRENT_TEST is set by pytest itself for
    # every test, so this needs no coordination with any test suite's conftest.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return

    # Don't early-return just because a URL is exported: a user may have
    # LITELLM_URL in their shell but keep the key/model only in the engine .env.
    # We still parse .env below and fill *only* the keys that aren't already set
    # (the `not os.environ.get(key)` guard), so an exported value is never
    # overridden — this just stops a lone URL from starving the key/model.
    from maistro_bootstrap.repo_root import find_maistro_engine_root

    # find_maistro_engine_root() already checks MAISTRO_REPO_ROOT first,
    # then walks upward from cwd.
    root = find_maistro_engine_root()
    if root is None:
        return

    env_file = root / ".env"
    if not env_file.is_file():
        return

    values = _parse_env_file(env_file)
    for key in _ENV_KEYS:
        if key in values and not os.environ.get(key):
            os.environ[key] = values[key]

    # Docker Compose's internal service name — unreachable from the host.
    for key in ("LITELLM_URL", "LITELLM_BASE_URL", "LITELLM_PROXY_URL"):
        val = os.environ.get(key, "")
        if "://litellm:" in val:
            os.environ[key] = val.replace("://litellm:", "://127.0.0.1:")


def _base_url() -> str:
    _ensure_env_loaded()
    return (
        os.environ.get("LITELLM_URL")
        or os.environ.get("LITELLM_BASE_URL")
        or os.environ.get("LITELLM_PROXY_URL")
        or ""
    ).rstrip("/")


def _api_key() -> str:
    _ensure_env_loaded()
    # Sandboxed/least-privilege deployments hold only a LiteLLM *virtual* key
    # (LITELLM_API_KEY / LITELLM_VIRTUAL_KEY) — accept those too so the agent
    # doesn't silently fall back to stub responses.
    return (
        os.environ.get("LITELLM_MASTER_KEY")
        or os.environ.get("LITELLM_PROXY_KEY")
        or os.environ.get("LITELLM_API_KEY")
        or os.environ.get("LITELLM_VIRTUAL_KEY")
        or ""
    )


def _default_model() -> str:
    # Must load .env before reading these — ResponsesAPICallable.__init__ calls
    # this at construction time, which is *before* the first _base_url() call, so
    # without this a fresh-terminal process (where MAISTRO_BUILDERS_MODEL/
    # DEFAULT_MODEL live only in .env, not the shell) would bake in the stale
    # fallback alias and 400 on the first turn.
    _ensure_env_loaded()
    return (
        os.environ.get("MAISTRO_BUILDERS_MODEL")
        or os.environ.get("DEFAULT_MODEL")
        or "claude-sonnet-4-6"
    )


def _tool_result_to_text(content: Any) -> str:
    """Flatten a tool_result's content into a plain string.

    The agent loop passes tool output as a str, but Anthropic also allows a list
    of content blocks — handle both so the OpenAI `tool` message always carries a
    string body.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", "") or str(block.get("content", "")))
            else:
                parts.append(str(block))
        return "".join(parts)
    return "" if content is None else str(content)


def _split_content_blocks(
    content: list[Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Split an Anthropic content-block list into (tool_calls, tool_results, text).

    tool_use blocks become OpenAI ``tool_calls`` entries; tool_result blocks
    become ``{"role": "tool", ...}`` messages; text (and anything unrecognised)
    is accumulated as plain string parts.
    """
    import json

    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            text_parts.append(str(block))
            continue
        btype = block.get("type")
        if btype == "tool_use":
            tool_calls.append(
                {
                    "id": block.get("id", "tc_0"),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {})),
                    },
                }
            )
        elif btype == "tool_result":
            tool_results.append(
                {
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id", ""),
                    "content": _tool_result_to_text(block.get("content", "")),
                }
            )
        elif btype == "text":
            text_parts.append(block.get("text", ""))
        else:
            text_parts.append(str(block))
    return tool_calls, tool_results, text_parts


def _to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate Anthropic-style tool blocks into OpenAI chat-completion shape.

    The agent loop keeps history in Anthropic form — an assistant turn's content
    is a list of ``{"type": "tool_use", ...}`` blocks, and tool outputs come back
    as a user message whose content is a list of ``{"type": "tool_result", ...}``
    blocks. LiteLLM's ``/v1/chat/completions`` is OpenAI-shaped and rejects those
    (``invalid content type=tool_result``), so on the *request* side we convert:
      - assistant ``tool_use`` blocks -> an assistant message with ``tool_calls``
      - user ``tool_result`` blocks   -> one ``{"role": "tool", ...}`` message each
    Plain string-content messages pass through untouched, so the common
    (no-tool) path is unaffected.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            out.append(msg)
            continue

        tool_calls, tool_results, text_parts = _split_content_blocks(content)

        if tool_results:
            out.extend(tool_results)
            leftover = "".join(text_parts).strip()
            if leftover:
                out.append({"role": "user", "content": leftover})
        elif tool_calls:
            out.append(
                {
                    "role": msg.get("role", "assistant"),
                    "content": "".join(text_parts),
                    "tool_calls": tool_calls,
                }
            )
        else:
            out.append({"role": msg.get("role", "user"), "content": "".join(text_parts)})
    return out


def _tool_use_blocks(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAI-shaped tool_calls -> the tool_use block list the agent loop expects.
    Unparseable arguments degrade to `{}` rather than failing the whole turn."""
    import json

    blocks: list[dict[str, Any]] = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        try:
            inp = json.loads(fn.get("arguments", "{}"))
        except json.JSONDecodeError:
            inp = {}
        blocks.append(
            {
                "type": "tool_use",
                "id": tc.get("id", "tc_0"),
                "name": fn.get("name", ""),
                "input": inp,
            }
        )
    return blocks


# (attribute, header names in preference order). The `llm_provider-*` variants
# carry the real upstream provider's counters; the bare `x-ratelimit-*` are the
# gateway's own, used only as a fallback.
_RATE_HEADERS: list[tuple[str, list[str]]] = [
    (
        "_rate_remaining_tokens",
        [
            "llm_provider-x-ratelimit-remaining-tokens-minute",
            "llm_provider-x-ratelimit-remaining-tokens",
            "x-ratelimit-remaining-tokens",
        ],
    ),
    (
        "_rate_limit_tokens",
        [
            "llm_provider-x-ratelimit-limit-tokens-minute",
            "llm_provider-x-ratelimit-limit-tokens",
            "x-ratelimit-limit-tokens",
        ],
    ),
    (
        "_rate_remaining_reqs",
        [
            "llm_provider-x-ratelimit-remaining-req-minute",
            "llm_provider-x-ratelimit-remaining-requests-minute",
            "llm_provider-x-ratelimit-remaining-requests",
            "x-ratelimit-remaining-requests",
        ],
    ),
]
# Token fragments that identify an Anthropic-family alias routed through the
# gateway. Anthropic is the only provider whose caching needs an EXPLICIT
# cache_control breakpoint (OpenAI, vLLM, DeepSeek auto-cache a stable prefix);
# it is also the only one that accepts the structured-content shape below, so the
# marker is gated to these models and every other alias keeps the plain payload.
_ANTHROPIC_MODEL_MARKERS = ("claude", "anthropic", "sonnet", "opus", "haiku")


def _is_anthropic_model(model: str) -> bool:
    lowered = model.lower()
    return any(marker in lowered for marker in _ANTHROPIC_MODEL_MARKERS)


def _mark_prefix_cache(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach an ephemeral cache breakpoint to the first system message.

    Anthropic orders the request tools -> system -> messages and caches every
    block up to and including a breakpoint, so marking the system message caches
    the whole stable prefix (the large tool schemas AND the system prompt) in one
    breakpoint. The string content is promoted to a single text part carrying the
    ``cache_control`` marker; if there is no system message (unexpected for the
    builders loop) the messages are returned unchanged.
    """
    marked = False
    out: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if not marked and msg.get("role") == "system" and isinstance(content, str):
            out.append(
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": content,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            )
            marked = True
        else:
            out.append(msg)
    return out


class LiteLLMCallable:
    """Synchronous OpenAI-compatible callable backed by the LiteLLM proxy.

    Supports tool definitions in OpenAI function-calling format so the agent
    loop can dispatch read_file / write_file / run_tests / etc. through the
    gateway's tool-use flow without being tied to a single provider SDK.
    """

    def __init__(
        self,
        model: str | None = None,
        timeout: float = 120.0,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        prompt_cache: bool = False,
    ) -> None:
        self.model = model or _default_model()
        self.timeout = timeout
        # Opt-in Anthropic prompt caching: mark the stable prefix (tools + system)
        # with an ephemeral cache breakpoint so re-sending the identical prefix
        # across a variant's turns/cycles bills at ~10%. Off by default and a
        # no-op unless the routed model is Anthropic-family — every other provider
        # sees the byte-identical legacy payload, so this can never break a
        # non-Anthropic genome. Needs one live gateway validation before default-on.
        self.prompt_cache = prompt_cache
        # A competing genome's sampling temperature; None = provider default.
        self.temperature = temperature
        # Reasoning-model effort level ("low"/"medium"/"high"), the
        # temperature/top_p/top_k/(partial)max_tokens replacement on o-series,
        # GPT-5, Gemini-2.5-thinking, DeepSeek-R1, etc. Reasoning models reject an
        # explicit temperature outright, so __call__ sends one or the other, never
        # both — this takes priority when set.
        self.reasoning_effort = reasoning_effort
        # Router-agnostic rate-limit pacing state (updated from response headers).
        # See docs/model-rate-limit-headers.md — stays just under the provider
        # ceiling so we never 429-storm (which trips abuse revocation).
        self._rate_remaining_tokens: float | None = None
        self._rate_limit_tokens: float | None = None
        self._rate_remaining_reqs: float | None = None

    def _is_configured(self) -> bool:
        return bool(_base_url() and _api_key())

    def _throttle_if_near_limit(self) -> None:
        """Sleep out the current rate window when the last response said we are
        nearly out of requests or tokens."""
        import time as _time

        if self._rate_remaining_reqs is not None and self._rate_remaining_reqs <= 1:
            logger.info(
                "rate_pacer throttle: %.0f reqs left, waiting 60s for window",
                self._rate_remaining_reqs,
            )
            _time.sleep(60.0)
        elif (
            self._rate_limit_tokens
            and self._rate_remaining_tokens is not None
            and self._rate_remaining_tokens < 0.10 * self._rate_limit_tokens
        ):
            logger.info(
                "rate_pacer throttle: %.0f tokens left (limit %.0f), waiting 60s",
                self._rate_remaining_tokens,
                self._rate_limit_tokens,
            )
            _time.sleep(60.0)

    def _observe_rate_headers(self, resp: Any) -> None:
        """Record upstream rate-limit counters (llm_provider-* = the real
        upstream numbers; the bare x-ratelimit-* are the gateway's own)."""
        for attr, hdrs in _RATE_HEADERS:
            for h in hdrs:
                raw = getattr(resp, "headers", {}).get(h) if hasattr(resp, "headers") else None
                if raw:
                    with contextlib.suppress(ValueError):
                        setattr(self, attr, float(raw))
                    break

    def __call__(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 8192,
    ) -> dict[str, Any]:
        if not self._is_configured():
            logger.warning("LiteLLM gateway not configured — returning stub response")
            return {
                "content": (
                    "(LiteLLM not configured — set LITELLM_URL + LITELLM_MASTER_KEY. "
                    "54+ models available once connected.)"
                ),
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }

        body = self._build_request_body(messages, tools, max_tokens)

        # Router-agnostic rate-limit pacing: stay just under the provider
        # ceiling (reads llm_provider-* headers forwarded by the router;
        # works behind any router, not just LiteLLM). Throttles before calls
        # predicted to cross; backs off on 429 instead of tight-looping.
        import time as _time

        return self._post_with_pacing(body, _time)

    def _build_request_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Assemble the chat-completions payload.

        Split out of ``__call__`` when the Anthropic prompt-cache marker and the
        rate-limit pacing loop landed on the same method from two branches;
        together they pushed it past the complexity gate. Body assembly is the
        self-contained half.
        """
        oai_messages = _to_openai_messages(messages)
        # Anthropic-only, opt-in: mark the stable prefix so the identical
        # tools+system re-sent every turn/cycle is cache-billed. Non-Anthropic
        # models keep the exact legacy messages (byte-identical), so this never
        # perturbs their payload.
        if self.prompt_cache and _is_anthropic_model(self.model):
            oai_messages = _mark_prefix_cache(oai_messages)
        body: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "max_tokens": max_tokens,
            # RSI/evolve must never get cached responses — the agent's workspace
            # state changes every turn, so a cache hit returns stale tool output
            # that doesn't match the files the agent just wrote/read.
            "cache": {"no-cache": True, "no-store": True},
        }
        # reasoning_effort and temperature are mutually exclusive on reasoning
        # models (sending both 400s), so prefer reasoning_effort when set and
        # never send temperature alongside it. Neither set ⇒ provider default,
        # keeping the byte-identical default path for existing callers.
        if self.reasoning_effort is not None:
            body["reasoning_effort"] = self.reasoning_effort
        elif self.temperature is not None:
            body["temperature"] = self.temperature
        if tools:
            # LiteLLM forwards OpenAI-format tool definitions to every provider
            # that supports function-calling (Anthropic, OpenAI, Mistral, …).
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                    },
                }
                for t in tools
            ]
            body["tool_choice"] = "auto"

        return body

    def _post_with_pacing(self, body: dict[str, Any], _time: Any) -> dict[str, Any]:
        """Post ``body``, throttling ahead of the provider ceiling and retrying 429s."""
        for _attempt in range(4):  # 1 try + up to 3 429-retries
            self._throttle_if_near_limit()

            resp = httpx.post(
                f"{_base_url()}{os.environ.get('LLM_CHAT_PATH', '/v1/chat/completions')}",
                json=body,
                headers={"Authorization": f"Bearer {_api_key()}"},
                timeout=self.timeout,
            )

            self._observe_rate_headers(resp)

            if resp.status_code == 429:
                ra = (
                    getattr(resp, "headers", {}).get("retry-after", "60")
                    if hasattr(resp, "headers")
                    else "60"
                )
                try:
                    wait = min(float(ra), 120.0)
                except ValueError:
                    wait = 60.0
                logger.warning(
                    "rate_pacer 429, backing off %.0fs (attempt %d/4)", wait, _attempt + 1
                )
                _time.sleep(wait)
                continue
            if resp.status_code >= 400:
                raise RuntimeError(f"LiteLLM gateway {resp.status_code}: {resp.text[:500]}")
            break
        else:
            raise RuntimeError(f"LiteLLM gateway 429: exhausted retries. Last: {resp.text[:500]}")

        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        content = msg.get("content") or ""
        stop_reason = choice.get("finish_reason", "end_turn")

        # Normalise tool_calls into the same block-list shape the agent loop expects.
        if tool_calls := msg.get("tool_calls") or []:
            content = _tool_use_blocks(tool_calls)
            stop_reason = "tool_use"

        usage = data.get("usage", {})
        return {
            "content": content,
            "stop_reason": stop_reason,
            "usage": {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            },
        }


# Backwards-compat alias — the TUI imported this name.
ResponsesAPICallable = LiteLLMCallable
