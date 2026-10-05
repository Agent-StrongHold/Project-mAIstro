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
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

import httpx
import structlog
from pydantic import ValidationError

from maistro.agents.circuit_breaker import (
    CircuitOpenError,
    DomainCircuitBank,
    FailureDomain,
    llm_circuits,
    resolve_failure_domain,
)
from maistro.agents.prompts import CONDUCTOR_SYSTEM
from maistro.agents.types import ConductorOutput, LLMProviderError, PlanOutput, SubTask
from maistro.capabilities.admitted_model import AdmittedModelCalls
from maistro.capabilities.binding_store import BindingResolutionError
from maistro.capabilities.governed_invocation import InvocationApprovalRequired, InvocationDenied
from maistro.capabilities.invocation import (
    CapabilityUnavailable,
    EffectNotApplied,
    UnsafeEffectRetry,
)
from maistro.capabilities.model_chat import ModelChatRequest
from maistro.config.model_resolver import resolve_model
from maistro.config.models import DEFAULT_TIERS, Tier, TierConfig
from maistro.config.settings import get_settings
from maistro.constants import DESCRIPTION_LOG_PREVIEW_LEN
from maistro.credentials.router import CredentialScopeError
from maistro.observability.metrics import llm_errors_total, llm_requests_total
from maistro.observability.tracing import trace_agent
from maistro.providers.errors import ModelNotFoundError
from maistro.quota.invocation_quota import InvocationQuotaDenied
from maistro.tasks.models import TaskCreate

if TYPE_CHECKING:
    from maistro.providers.protocols import LLMRouter

OnResponseHook = Callable[[dict[str, Any], httpx.Response], None]

logger = structlog.get_logger()

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

    Physical HTTP is owned by the admitted model egress (no pydantic-ai).
    It always requests JSON output and validates the result into ConductorOutput.
    """
    litellm_key = os.environ.get("LITELLM_MASTER_KEY", "")
    api_key = litellm_key if litellm_key else "ollama"
    model_name = (model or "openai:maistro-default").removeprefix("openai:")
    system_prompt = CONDUCTOR_SYSTEM + _CONDUCTOR_JSON_SCHEMA
    return ConductorCall(
        model=model_name, base_url=base_url, api_key=api_key, system_prompt=system_prompt
    )


async def _governed_completion(
    call: ConductorCall,
    user_prompt: str,
    max_tokens: int,
    admitted_calls: AdmittedModelCalls,
    invocation_identity: tuple[str, str, str] | None,
    invocation_number: int,
    *,
    timeout: float | None = None,
) -> str:
    """Resolve persisted execution and configured Binding before any model effect."""
    result = await admitted_calls.complete(
        identity=invocation_identity,
        timeout_s=timeout,
        effect_key=f"conductor-llm-{invocation_number}",
        request=ModelChatRequest(
            model=call.model,
            messages=[
                {"role": "system", "content": call.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        ),
    )
    body = result.body
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMProviderError("conductor: governed gateway returned no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise LLMProviderError("conductor: governed gateway returned no content")
    return content


async def _call_gateway(
    call: ConductorCall,
    user_prompt: str,
    max_tokens: int,
    timeout: float,
    on_response: OnResponseHook | None = None,
    admitted_calls: AdmittedModelCalls | None = None,
    invocation_identity: tuple[str, str, str] | None = None,
    invocation_number: int = 0,
) -> str:
    """Complete only through canonical admission; there is no direct HTTP fallback.

    ``timeout`` bounds both the outer call and the approved Provider's HTTP.
    ``on_response`` is a retired compatibility parameter: canonical Invocation
    terminalization owns usage evidence. A hook cannot authorize raw HTTP.
    """
    if admitted_calls is None:
        raise LLMProviderError("conductor: admitted model calls are not configured")
    return await _governed_completion(
        call,
        user_prompt,
        max_tokens,
        admitted_calls,
        invocation_identity,
        invocation_number,
        timeout=timeout,
    )


def _is_retryable(exc: Exception, *, response_completed: bool = False) -> bool:
    """Retry proven non-dispatch or repair validation after a completed response.

    HTTP failures and timeouts can leave an UNKNOWN Invocation. A new effect
    key must not bypass its ambiguity fence. Provider JSON decoding can fail
    before terminalization too, so only conductor-side validation of a returned
    response may start a distinct bounded repair operation.
    """
    return isinstance(exc, EffectNotApplied) or (
        response_completed and isinstance(exc, (json.JSONDecodeError, ValidationError))
    )


def _parse_json_output(raw: str) -> ConductorOutput:
    """Parse a raw JSON string from the gateway into a validated ConductorOutput."""
    data = json.loads(raw)
    return ConductorOutput.model_validate(data)


def conductor_failure_domain(call: ConductorCall) -> FailureDomain:
    """The failure domain one conductor gateway call depends on (#1203).

    Scoped to what can fail independently: the sanitized gateway endpoint x
    the upstream routing target the model string names — never one global
    process flag.
    """
    return resolve_failure_domain(model=call.model, base_url=call.base_url)


async def _admitted_fallback_call(
    call: ConductorCall,
    circuits: DomainCircuitBank,
    router: LLMRouter,
) -> ConductorCall | None:
    """First fallback-chain candidate whose failure domain admits traffic.

    The chain comes from the router's registry-declared ``fallback_to`` edges
    (ADR-079), so fallback stays inside canonical routing configuration — it
    never widens what the call may touch. Every candidate still crosses the
    same configured Binding and canonical Invocation boundary. ``None`` when no
    candidate is admitting.
    """
    try:
        chain = await router.fallback_chain(call.model)
    except ModelNotFoundError:
        return None
    for candidate in chain:
        if candidate.name == call.model:
            continue
        candidate_domain = resolve_failure_domain(
            model=candidate.name, base_url=call.base_url, provider=candidate.provider
        )
        if circuits.admit(candidate_domain):
            return replace(call, model=candidate.name)
    return None


async def _admit_call(
    call: ConductorCall,
    bank: DomainCircuitBank,
    router: LLMRouter | None,
) -> tuple[ConductorCall, FailureDomain]:
    """Resolve the (call, domain) pair allowed to proceed to the gateway.

    Returns the original call when its failure domain admits traffic, or the
    first router-declared fallback candidate whose own domain admits it.
    Raises :class:`CircuitOpenError` when still blocked; the re-check also
    absorbs the race where the domain recovered while the fallback chain was
    resolving — in that case the original call simply proceeds. The raised
    error names the blocking breaker (gateway first) and fails fast.
    """
    domain = conductor_failure_domain(call)
    if bank.admit(domain):
        return call, domain
    fallback_call: ConductorCall | None = None
    if router is not None:
        fallback_call = await _admitted_fallback_call(call, bank, router)
    if fallback_call is not None:
        return fallback_call, conductor_failure_domain(fallback_call)
    if not bank.admit(domain):
        raise CircuitOpenError(bank.blocking_breaker(domain) or bank.breaker(domain))
    return call, domain


async def _configured_call(
    call: ConductorCall,
    admitted_calls: AdmittedModelCalls | None,
    invocation_identity: tuple[str, str, str] | None,
    router: LLMRouter | None,
) -> tuple[ConductorCall, LLMRouter | None]:
    """Read the configured physical target before its circuit is consulted."""
    if admitted_calls is None:
        raise LLMProviderError("conductor requires admitted model-call authority")
    pinned_model = await admitted_calls.pinned_model(identity=invocation_identity)
    actual_call = replace(
        call,
        model=pinned_model or call.model,
        base_url=admitted_calls.gateway_base_url,
    )
    # A configured pin cannot fall back. Circuit selection must describe
    # the actual pinned Provider and endpoint before any admission check.
    return actual_call, None if pinned_model else router


async def _run_with_retry(
    call: ConductorCall,
    prompt: str,
    tier_config: TierConfig,
    max_tokens: int,
    on_response: OnResponseHook | None = None,
    admitted_calls: AdmittedModelCalls | None = None,
    invocation_identity: tuple[str, str, str] | None = None,
    circuits: DomainCircuitBank | None = None,
    router: LLMRouter | None = None,
) -> ConductorOutput:
    """Call the gateway, retrying only proven-safe failures or response repair.

    Circuit scope (#1203, ADR-038): breaker state is keyed to the call's
    failure domain — gateway endpoint x upstream provider — so one flaky
    provider cannot open a breaker that blocks unrelated healthy providers.
    A gateway-level breaker intentionally represents failure of the shared
    endpoint itself (connection refused → every provider behind it blocked).

    When the current model's domain is blocked and a ``router`` is supplied,
    admission falls forward through the router's declared fallback chain to
    the first candidate whose own domain admits traffic. Without a router the
    blocked call fails with :class:`CircuitOpenError`, as before.
    """
    from maistro.runs.store import RunIntegrityError

    bank = circuits if circuits is not None else llm_circuits
    call, router = await _configured_call(call, admitted_calls, invocation_identity, router)
    call, domain = await _admit_call(call, bank, router)

    last_exc: Exception | None = None
    shared_failure = False

    for attempt in range(tier_config.max_llm_retries):
        response_completed = False
        try:
            llm_requests_total.inc()
            raw = await asyncio.wait_for(
                _call_gateway(
                    call,
                    prompt,
                    max_tokens,
                    tier_config.timeout,
                    on_response,
                    admitted_calls,
                    invocation_identity,
                    attempt,
                ),
                timeout=tier_config.timeout,
            )
            response_completed = True
            result = _parse_json_output(raw)
            bank.record_success(domain)
            return result
        except (
            BindingResolutionError,
            InvocationDenied,
            InvocationApprovalRequired,
            InvocationQuotaDenied,
            CredentialScopeError,
            CapabilityUnavailable,
            UnsafeEffectRetry,
            RunIntegrityError,
        ):
            # These typed admission refusals prove no Provider dispatch. They
            # neither authorize retries nor describe the Provider's health.
            raise
        except TimeoutError:
            # A slow response is routed-upstream evidence, not proof the shared
            # endpoint died — a dead gateway refuses connections instead.
            await logger.awarning(
                "llm_timeout",
                attempt=attempt + 1,
                max_retries=tier_config.max_llm_retries,
                timeout=tier_config.timeout,
            )
            bank.record_failure(domain)
            llm_errors_total.inc(error_type="non_retryable")
            raise
        except Exception as exc:
            if _is_retryable(exc, response_completed=response_completed):
                last_exc = exc
                # Both connect failures are shared-endpoint evidence: the
                # TCP/TLS handshake to the gateway never completed, so no
                # routed upstream could be at fault.
                shared_failure = isinstance(exc, EffectNotApplied) and isinstance(
                    exc.__cause__, (httpx.ConnectError, httpx.ConnectTimeout)
                )
                await logger.awarning(
                    "llm_transient_error",
                    attempt=attempt + 1,
                    max_retries=tier_config.max_llm_retries,
                    error=str(exc),
                )
            else:
                # A non-retryable response came from the routed upstream, not
                # from the shared endpoint — scope it to this provider only.
                bank.record_failure(domain)
                llm_errors_total.inc(error_type="non_retryable")
                raise

        bank.record_failure(domain, shared=shared_failure)
        llm_errors_total.inc(error_type="retryable")

        # Exponential backoff with jitter before retry
        if attempt < tier_config.max_llm_retries - 1:
            delay = tier_config.initial_backoff * (2**attempt) + random.uniform(0, 1)  # nosec B311 — retry jitter, not crypto
            await asyncio.sleep(delay)

    raise LLMProviderError(
        f"LLM call failed after {tier_config.max_llm_retries} retries: {last_exc}"
    )


@trace_agent("conductor")
async def run_task(
    task: TaskCreate,
    on_response: OnResponseHook | None = None,
    *,
    admitted_calls: AdmittedModelCalls | None = None,
    invocation_identity: tuple[str, str, str] | None = None,
    router: LLMRouter | None = None,
) -> ConductorOutput:
    """Execute a full engineering task through the conductor pipeline.

    This is the main entry point for task execution. It:
    1. Selects the appropriate tier/model configuration
    2. Builds the conductor agent
    3. Runs the agent with timeout and retry logic
    4. Returns structured output

    ``admitted_calls`` resolves persisted canonical Run/NodeRun/Attempt records
    and an operator-configured Binding on every retry. Each retry gets its own
    Invocation effect key. ``on_response`` is retained for signature compatibility
    only; canonical Invocation terminalization owns usage recording.

    `router`, if given, lets a provider-scoped circuit block (#1203) fall
    forward through the router's declared fallback chain to a healthy
    candidate instead of failing; without one a blocked domain raises
    `CircuitOpenError`.

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
        call,
        prompt,
        tier_config,
        max_tokens=max_tokens,
        on_response=on_response,
        admitted_calls=admitted_calls,
        invocation_identity=invocation_identity,
        router=router,
    )
    await logger.ainfo("conductor_complete", success=result.success)
    return result
