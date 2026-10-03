"""Conductor agent — top-level orchestrator for engineering tasks.

Phase 1: Single Pydantic AI agent that handles plan/code/review in one pass.
Phase 2 will split this into sub-agents (planner, coder, reviewer, scout).

For Ollama models that don't support complex tool schemas, the conductor falls
back to JSON-prompt mode: it instructs the model to return JSON directly and
parses/validates the response with Pydantic.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from pydantic import ValidationError

from maistro.agents.circuit_breaker import CircuitOpenError, llm_circuit
from maistro.agents.prompts import CONDUCTOR_SYSTEM
from maistro.agents.types import ConductorOutput, LLMProviderError, PlanOutput, SubTask
from maistro.config.model_resolver import resolve_model
from maistro.config.models import DEFAULT_TIERS, Tier, TierConfig
from maistro.config.settings import get_settings
from maistro.constants import DESCRIPTION_LOG_PREVIEW_LEN
from maistro.http import shared_client
from maistro.observability.metrics import llm_errors_total, llm_requests_total
from maistro.observability.tracing import trace_agent
from maistro.tasks.models import TaskCreate

OnResponseHook = Callable[[dict[str, Any], httpx.Response], None]

logger = structlog.get_logger()

# HTTP status codes that indicate transient failures worth retrying
_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}

# JSON schema appended to the system prompt for Ollama JSON-mode fallback
_CONDUCTOR_JSON_SCHEMA = """\

You MUST respond with valid JSON matching this exact schema (no markdown, no extra text):
{
  "plan": {
    "summary": "string — brief plan summary",
    "subtasks": [
      {"title": "string", "description": "string"}
    ]
  },
  "final_answer": "string — concise summary of what you would implement",
  "success": true
}
"""


def _get_tier_config(tier: int | None) -> TierConfig:
    t = Tier(tier) if tier and tier in [e.value for e in Tier] else Tier.STANDARD
    return DEFAULT_TIERS[t]


@dataclass(frozen=True)
class ConductorCall:
    """Resolved parameters for one conductor LLM call against the OpenAI-compatible gateway."""

    model: str
    base_url: str | None
    api_key: str
    system_prompt: str


def build_conductor(
    model: str | None = None,
    base_url: str | None = None,
    use_json_mode: bool = False,  # retained for signature compatibility; JSON is now always used
) -> ConductorCall:
    """Resolve the call parameters for the conductor.

    The conductor talks directly to the OpenAI-compatible LiteLLM gateway over HTTP
    (no pydantic-ai). It always requests JSON output and validates the result into
    ConductorOutput — i.e. the former Ollama JSON-mode path is now the only path.
    """
    litellm_key = os.environ.get("LITELLM_MASTER_KEY", "")
    api_key = litellm_key if litellm_key else "ollama"
    model_name = (model or "openai:maistro-default").removeprefix("openai:")
    system_prompt = CONDUCTOR_SYSTEM + _CONDUCTOR_JSON_SCHEMA
    return ConductorCall(
        model=model_name, base_url=base_url, api_key=api_key, system_prompt=system_prompt
    )


async def _call_gateway(
    call: ConductorCall,
    user_prompt: str,
    max_tokens: int,
    timeout: float,
    on_response: OnResponseHook | None = None,
) -> str:
    """POST one chat-completion to the OpenAI-compatible gateway; return the message content.

    `on_response`, if given, is invoked with the parsed body and the raw response
    right before `content` is returned — the same seam `pm_llm_call.maistro_llm_call`
    exposes for `maistro.quota.recorder` to hook into. Optional and additive; a
    failing hook is logged and swallowed since instrumentation on an already-
    successful call must never turn into a failure the caller has to handle.
    """
    if not call.base_url:
        raise LLMProviderError(
            "conductor: no gateway base_url configured (set MAISTRO_LLM_BASE_URL)"
        )
    url = call.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": call.model,
        "messages": [
            {"role": "system", "content": call.system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens,
    }
    headers = {"Authorization": f"Bearer {call.api_key}"}
    async with shared_client(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    if on_response is not None:
        try:
            on_response(data, resp)
        except Exception:
            await logger.awarning("conductor_on_response_hook_failed", exc_info=True)
    return str(data["choices"][0]["message"]["content"])


def _is_retryable(exc: Exception) -> bool:
    """Check if an exception represents a transient failure worth retrying."""
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return True
    if isinstance(exc, httpx.ConnectError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS_CODES
    # A malformed/invalid JSON response is often transient — re-prompt may fix it.
    return isinstance(exc, (json.JSONDecodeError, ValidationError, KeyError))


def _parse_json_output(raw: str) -> ConductorOutput:
    """Parse a raw JSON string from the gateway into a validated ConductorOutput."""
    data = json.loads(raw)
    return ConductorOutput.model_validate(data)


async def _run_with_retry(
    call: ConductorCall,
    prompt: str,
    tier_config: TierConfig,
    max_tokens: int,
    on_response: OnResponseHook | None = None,
) -> ConductorOutput:
    """Call the gateway with timeout and retry logic for transient failures."""
    if not llm_circuit.allow_request():
        raise CircuitOpenError(llm_circuit)

    last_exc: Exception | None = None

    for attempt in range(tier_config.max_llm_retries):
        try:
            llm_requests_total.inc()
            raw = await asyncio.wait_for(
                _call_gateway(call, prompt, max_tokens, tier_config.timeout, on_response),
                timeout=tier_config.timeout,
            )
            result = _parse_json_output(raw)
            llm_circuit.record_success()
            return result
        except TimeoutError as exc:
            last_exc = exc
            await logger.awarning(
                "llm_timeout",
                attempt=attempt + 1,
                max_retries=tier_config.max_llm_retries,
                timeout=tier_config.timeout,
            )
        except Exception as exc:
            if _is_retryable(exc):
                last_exc = exc
                await logger.awarning(
                    "llm_transient_error",
                    attempt=attempt + 1,
                    max_retries=tier_config.max_llm_retries,
                    error=str(exc),
                )
            else:
                llm_circuit.record_failure()
                llm_errors_total.inc(error_type="non_retryable")
                raise

        llm_circuit.record_failure()
        llm_errors_total.inc(error_type="retryable")

        # Exponential backoff with jitter before retry
        if attempt < tier_config.max_llm_retries - 1:
            delay = tier_config.initial_backoff * (2**attempt) + random.uniform(0, 1)  # nosec B311 — retry jitter, not crypto
            await asyncio.sleep(delay)

    raise LLMProviderError(
        f"LLM call failed after {tier_config.max_llm_retries} retries: {last_exc}"
    )


@trace_agent("conductor")
async def run_task(task: TaskCreate, on_response: OnResponseHook | None = None) -> ConductorOutput:
    """Execute a full engineering task through the conductor pipeline.

    This is the main entry point for task execution. It:
    1. Selects the appropriate tier/model configuration
    2. Builds the conductor agent
    3. Runs the agent with timeout and retry logic
    4. Returns structured output

    `on_response`, if given, is forwarded to `_call_gateway` on every retry attempt —
    the same additive quota-recording seam `pm_llm_call.maistro_llm_call` exposes.

    If maistro_dry_run is set in settings, returns a mock result without calling any LLM.
    """
    settings = get_settings()

    # Dry-run mode — return mock result without LLM call
    if settings.maistro_dry_run:
        await logger.ainfo(
            "conductor_dry_run", description=task.description[:DESCRIPTION_LOG_PREVIEW_LEN]
        )
        return ConductorOutput(
            plan=PlanOutput(
                summary=f"[DRY RUN] Plan for: {task.description}",
                subtasks=[
                    SubTask(title="Analyze requirements", description=task.description),
                    SubTask(title="Implement solution", description="Write the code changes"),
                    SubTask(title="Add tests", description="Write test coverage"),
                ],
            ),
            final_answer=f"[DRY RUN] Task planned: {task.description}",
            success=True,
        )

    # MAJ-08: Enforce token budget from settings
    max_tokens = settings.max_tokens_per_task

    tier_config = _get_tier_config(task.tier)
    resolved_model, base_url, _use_json_mode = resolve_model(tier_config.model)

    await logger.ainfo(
        "conductor_start",
        tier=tier_config.tier,
        model=resolved_model,
        base_url=base_url or "default",
        json_mode=True,
        max_tokens=max_tokens,
        description=task.description[:DESCRIPTION_LOG_PREVIEW_LEN],
    )

    call = build_conductor(model=resolved_model, base_url=base_url)

    constraints_text = "\n".join(f"- {c}" for c in task.constraints) if task.constraints else "None"
    prompt = (
        f"Task: {task.description}\n\nWorkspace: {task.workspace}\nConstraints:\n{constraints_text}"
    )

    result = await _run_with_retry(
        call, prompt, tier_config, max_tokens=max_tokens, on_response=on_response
    )
    await logger.ainfo("conductor_complete", success=result.success)
    return result
