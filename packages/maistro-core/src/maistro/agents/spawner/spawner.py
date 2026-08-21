"""Spawner — single agent execution funnel (ADR-009)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol, runtime_checkable

from maistro.agents.recipes import RecipeRegistry
from maistro.agents.spawner.variant_selector import VariantSelector
from maistro.agents.spec.agent_spec import AgentOutput, AgentSpec, ErrorType
from maistro.agents.spec.schemas import resolve_schema
from maistro.agents.spec.structured_output import StructuredOutputParser

logger = logging.getLogger(__name__)

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+(instructions|prompts|rules)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a|an|the)\s+", re.IGNORECASE),
    re.compile(r"<\|.*?(system|endoftext|im_start).*?\|>", re.IGNORECASE),
    re.compile(r"\[\[.*?SYSTEM.*?\]\]", re.IGNORECASE),
    re.compile(r"(don'?t|never)\s+(tell|reveal|show)\s+(the\s+)?(user|human)", re.IGNORECASE),
    re.compile(r"(steal|exfiltrate|dump)\s+(credentials?|passwords?|tokens?)", re.IGNORECASE),
]


def _is_suspicious(text: str) -> bool:
    return any(p.search(text) for p in _INJECTION_PATTERNS)


def _sanitize(text: str) -> str:
    result = text
    for p in _INJECTION_PATTERNS:
        result = p.sub("[REDACTED]", result)
    return result


@runtime_checkable
class LLMCaller(Protocol):
    async def call(
        self,
        system: str,
        user: str,
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        tier: int,
        lane: str,
    ) -> dict[str, Any]: ...


class _PromptManager(Protocol):
    def get_prompt(self, name: str, *, variables: dict[str, str], label: str) -> str | None: ...


class Spawner:
    """Single entry point for all agent executions."""

    def __init__(
        self,
        llm_caller: LLMCaller,
        prompt_manager: _PromptManager | None = None,
        langfuse_tracer: object | None = None,
        variant_selector: VariantSelector | None = None,
        recipe_registry: RecipeRegistry | None = None,
    ) -> None:
        self._llm = llm_caller
        self._pm: _PromptManager | None = prompt_manager
        self._tracer = langfuse_tracer
        self._vs = variant_selector
        self._rr = recipe_registry
        self._parser = StructuredOutputParser(max_retries=2)

    async def spawn(self, spec: AgentSpec) -> AgentOutput:
        spec = spec.with_defaults()
        self._apply_recipe(spec)
        result_type = resolve_schema(spec.result_type) if spec.result_type else None
        output = AgentOutput(
            agent_id=spec.agent_id,
            role=spec.role,
            task_id=spec.task_id,
            subtask_id=spec.subtask_id,
            attempt=spec.attempt,
            tier_used=spec.tier,
            variant_used=spec.prompt_label,
        )
        span_id = self._open_span(spec, output)
        try:
            await self._execute(spec, result_type, output)
        finally:
            output.mark_complete()
            self._close_span(spec, span_id, output)
        return output

    def _apply_recipe(self, spec: AgentSpec) -> None:
        if not (spec.recipe_name and self._rr):
            return
        recipe = self._rr.get(spec.recipe_name)
        if not recipe:
            return
        if not spec.result_type and recipe.result_schema:
            spec.result_type = recipe.result_schema
        if not spec.prompt_name:
            spec.prompt_name = recipe.prompt_name
        if spec.temperature is None:
            spec.temperature = recipe.temperature
        if spec.max_tokens is None:
            spec.max_tokens = recipe.max_tokens
        if self._vs and len(recipe.prompt_variants) > 1:
            spec.prompt_label = self._vs.select(recipe)

    def _open_span(self, spec: AgentSpec, output: AgentOutput) -> str | None:
        if not (self._tracer and spec.langfuse_trace_id):
            return None
        try:
            span_id = getattr(self._tracer, "trace_spawn", lambda **_: None)(
                trace_id=spec.langfuse_trace_id,
                agent_id=spec.agent_id,
                role=spec.role.value,
                task_id=spec.task_id,
                subtask_id=spec.subtask_id,
                tier=spec.tier,
            )
            output.langfuse_span_id = span_id
            return span_id
        except Exception as exc:
            logger.debug("Langfuse span creation failed: %s", exc)
            return None

    def _close_span(self, spec: AgentSpec, span_id: str | None, output: AgentOutput) -> None:
        if not (self._tracer and span_id and spec.langfuse_trace_id):
            return
        try:
            getattr(self._tracer, "end_spawn_span", lambda **_: None)(
                trace_id=spec.langfuse_trace_id,
                span_id=span_id,
                success=output.success,
            )
        except Exception as exc:
            logger.debug("Langfuse span close failed: %s", exc)

    async def _execute(
        self, spec: AgentSpec, result_type: type | None, output: AgentOutput
    ) -> None:
        try:
            system_prompt, user_prompt = self._build_prompts(spec)
            if result_type:
                system_prompt = self._parser.inject_schema(system_prompt, result_type)
            result = await self._llm.call(
                system_prompt,
                user_prompt,
                model=spec.model_override or "default",
                temperature=spec.temperature if spec.temperature is not None else 0.7,
                max_tokens=spec.max_tokens or 4096,
                tier=spec.tier,
                lane=spec.lane.value,
            )
            output.output = result.get("content", "")
            output.model_used = result.get("model")
            output.tokens_used = result.get("usage", {})
            output.success = True
            output.output_parsed = self._parse_output(output.output, result_type)
        except TimeoutError as exc:
            output.mark_error(f"Timeout: {exc}", ErrorType.TIMEOUT)
        except Exception as exc:
            error_str = str(exc)
            if "safety" in error_str.lower() or "policy" in error_str.lower():
                output.mark_error(error_str, ErrorType.SAFETY_VIOLATION)
            else:
                output.mark_error(error_str, ErrorType.MODEL_ERROR)

    def _parse_output(self, raw: str, result_type: type | None) -> dict[str, Any] | None:
        if result_type:
            try:
                return self._parser.parse(raw, result_type).model_dump()
            except Exception as _exc:
                __import__("logging").getLogger("maistro.agents.spawner.spawner").warning(
                    "error_swallowed file=%s line=%d: %s",
                    "packages/maistro-core/src/maistro/agents/spawner/spawner.py",
                    178,
                    _exc,
                )
                pass
        return _try_parse_json(raw)

    def _build_prompts(self, spec: AgentSpec) -> tuple[str, str]:
        system_parts: list[str] = []

        for key in ("layer0", "layer1", "layer2", "knowledge"):
            if key in spec.context:
                system_parts.append(spec.context[key])

        for agent_name, output_text in spec.upstream_outputs.items():
            if _is_suspicious(output_text):
                logger.warning("Upstream output from %s flagged — sanitizing", agent_name)
                output_text = _sanitize(output_text)
            system_parts.append(f"=== {agent_name.upper()} OUTPUT ===\n{output_text}")

        if self._pm and spec.prompt_name:
            try:
                role_prompt = self._pm.get_prompt(
                    spec.prompt_name,
                    variables={
                        "task_id": spec.task_id,
                        "subtask_id": spec.subtask_id,
                        "description": spec.description,
                        **spec.prompt_variables,
                    },
                    label=spec.prompt_label,
                )
                if role_prompt:
                    system_parts.append(role_prompt)
            except Exception as exc:
                logger.debug("PromptManager error: %s", exc)

        system_prompt = "\n\n".join(p for p in system_parts if p)
        user_prompt = f"## Task\n{spec.description}"
        return system_prompt, user_prompt

    async def close(self) -> None:
        pass


def _try_parse_json(text: str) -> dict[str, Any] | None:
    import contextlib

    cleaned = text.strip()
    if "```json" in cleaned:
        with contextlib.suppress(IndexError):
            cleaned = cleaned.split("```json")[1].split("```")[0]
    elif "```" in cleaned:
        with contextlib.suppress(IndexError):
            cleaned = cleaned.split("```")[1].split("```")[0]
    try:
        return json.loads(cleaned)  # type: ignore[no-any-return]
    except (json.JSONDecodeError, TypeError):
        return None
