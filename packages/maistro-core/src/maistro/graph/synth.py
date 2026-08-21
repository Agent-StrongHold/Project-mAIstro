"""DAG synthesis protocol — turn a natural-language objective into a GraphConfig.

Two implementations ship here:
  - `RuleDagSynthesizer`: deterministic rule-based synthesizer for tests and
    simple linear pipelines. Always returns scout → coder → reviewer.
  - `LLMDagSynthesizer`: uses an LLM to generate the DAG structure. Callers
    inject an `llm_call` compatible with `maistro.graph.node` conventions
    and supply a JSON schema the model is prompted to follow.

Both satisfy the `DagSynthesizer` Protocol so `AgentSynthDagNode` can accept
either via DI without coupling to a specific implementation.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from maistro.graph.types import AgentRole, GraphConfig, GraphEdge

logger = logging.getLogger("maistro.graph.synth")

_SYNTH_SYSTEM_PROMPT = """\
You are a DAG architect. Given an objective, produce a minimal directed acyclic graph of agent \
nodes to accomplish it.

Respond with a JSON object matching this schema exactly:
{
  "nodes": ["node_kind_or_role", ...],
  "edges": [{"from_node": "...", "to_node": "..."}, ...],
  "entry": "first_node",
  "rationale": "one sentence"
}

Use only these node kinds unless available_kinds is specified: \
planner, coder, reviewer, scout, conductor, llm.summarize, transform.extract_field.
Keep it small (max_nodes constraint applies).
"""


def _strip_code_fence(text: str) -> str:
    if "```" not in text:
        return text
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else text


def _coerce_role(value: str) -> AgentRole | str:
    try:
        return AgentRole(value)
    except ValueError:
        return value


@dataclass(frozen=True)
class SynthRequest:
    objective: str
    constraints: list[str] = field(default_factory=list)
    available_kinds: list[str] = field(default_factory=list)
    max_nodes: int = 8


@dataclass
class SynthResult:
    graph_config: GraphConfig
    rationale: str
    synthesized_kinds: list[str] = field(default_factory=list)


@runtime_checkable
class DagSynthesizer(Protocol):
    """Produce a `GraphConfig` from a `SynthRequest`."""

    async def synthesize(self, request: SynthRequest) -> SynthResult: ...


class RuleDagSynthesizer:
    """Deterministic synthesizer: always emits a scout → coder → reviewer pipeline.

    Used in tests and as a fallback when no LLM is available.
    """

    async def synthesize(self, request: SynthRequest) -> SynthResult:
        nodes: list[AgentRole | str] = [AgentRole.SCOUT, AgentRole.CODER, AgentRole.REVIEWER]
        edges = [
            GraphEdge(from_role=AgentRole.SCOUT, to_role=AgentRole.CODER),
            GraphEdge(from_role=AgentRole.CODER, to_role=AgentRole.REVIEWER),
        ]
        config = GraphConfig(nodes=nodes, edges=edges, entry=AgentRole.SCOUT)
        return SynthResult(
            graph_config=config,
            rationale=f"rule-based scout→coder→reviewer for: {request.objective[:60]}",
            synthesized_kinds=[str(n) for n in nodes],
        )


class LLMDagSynthesizer:
    """LLM-driven synthesizer. Injects an llm_call compatible with NodeRun semantics.

    The caller must wire in an `llm_call` and optionally a list of available
    node kinds to constrain the LLM's output.
    """

    def __init__(
        self,
        llm_call: Callable[..., Awaitable[Any]],
        model: str = "default",
        temperature: float = 0.2,
        fallback: DagSynthesizer | None = None,
    ) -> None:
        self._llm_call = llm_call
        self._model = model
        self._temperature = temperature
        self._fallback: DagSynthesizer = fallback or RuleDagSynthesizer()

    async def synthesize(self, request: SynthRequest) -> SynthResult:
        kinds_hint = (
            f"Limit to these kinds: {request.available_kinds}" if request.available_kinds else ""
        )
        constraint_hint = (
            "\n".join(f"- {c}" for c in request.constraints) if request.constraints else "none"
        )
        user_msg = (
            f"Objective: {request.objective}\n"
            f"Max nodes: {request.max_nodes}\n"
            f"Constraints:\n{constraint_hint}\n"
            f"{kinds_hint}"
        )
        messages = [
            {"role": "system", "content": _SYNTH_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]
        try:
            raw = await self._llm_call(messages, model=self._model, temperature=self._temperature)
            text = raw if isinstance(raw, str) else (raw.get("content") or raw.get("text") or "")
            return self._parse(text, request)
        except Exception as exc:
            logger.warning("LLMDagSynthesizer failed (%s), using fallback", exc)
            return await self._fallback.synthesize(request)

    def _parse(self, text: str, request: SynthRequest) -> SynthResult:
        data: dict[str, Any] = json.loads(_strip_code_fence(text.strip()))

        raw_nodes: list[str] = data.get("nodes") or []
        raw_edges: list[dict[str, str]] = data.get("edges") or []
        entry_raw: str = data.get("entry") or (raw_nodes[0] if raw_nodes else AgentRole.PLANNER)
        rationale: str = data.get("rationale") or ""

        nodes = [_coerce_role(n) for n in raw_nodes[: request.max_nodes]]
        edges = [
            GraphEdge(from_role=e["from_node"], to_role=e.get("to_node"))
            for e in raw_edges
            if "from_node" in e
        ]

        config = GraphConfig(nodes=nodes, edges=edges, entry=_coerce_role(entry_raw))
        return SynthResult(
            graph_config=config,
            rationale=rationale,
            synthesized_kinds=[str(n) for n in nodes],
        )
