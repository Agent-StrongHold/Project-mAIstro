"""Proportionality judge — the "need" axis of DAG shape review.

Neither Warden (threat detection) nor Sentinel (policy/budget authorization)
answers "is this decomposition actually proportional to the objective."
That's a reasoning call, not a policy or safety call, so it gets its own
lightweight critic — same cost/latency shape as Warden's L3 classifier
(cheap model, few-shot, ~100-200ms), scoring proportionality instead of
threat.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from maistro.security.dag_shape.types import ProposedDagShape

if TYPE_CHECKING:
    from maistro.security._types import LLMClient

logger = logging.getLogger("maistro.security.dag_shape.proportionality")

_SYSTEM_PROMPT = """\
You are a proportionality critic for an AI agent orchestration platform.

You are given an objective and a proposed decomposition into agent nodes. \
A large decomposition is not inherently wrong -- many small focused nodes can \
outperform one large model when the objective genuinely branches. Your job is \
to judge whether THIS shape is proportional to THIS objective, not to prefer \
small shapes.

Respond with ONLY a JSON object:
{"justified": true or false, "add": ["kind", ...], "drop": ["kind", ...], "reason": "one sentence"}

"add" lists node kinds missing for the objective to be safely/completely covered.
"drop" lists node kinds in the proposal that don't serve the objective.
Leave both empty if the shape is already proportional."""


@dataclass(frozen=True)
class ProportionalityVerdict:
    justified: bool
    add: tuple[str, ...] = field(default_factory=tuple)
    drop: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""


@runtime_checkable
class ProportionalityJudge(Protocol):
    async def judge(self, shape: ProposedDagShape) -> ProportionalityVerdict: ...


class RuleProportionalityJudge:
    """Deterministic fallback: always justified. Used in tests and when no LLM is wired."""

    async def judge(self, shape: ProposedDagShape) -> ProportionalityVerdict:
        return ProportionalityVerdict(justified=True, reason="no LLM judge configured")


class LLMProportionalityJudge:
    """Real critic: asks a cheap model whether the shape is proportional."""

    def __init__(self, llm: LLMClient, model: str = "auto") -> None:
        self._llm = llm
        self._model = model

    async def judge(self, shape: ProposedDagShape) -> ProportionalityVerdict:
        try:
            messages = self._build_prompt(shape)
            response = await self._llm.complete(messages, self._model)
            choices = response.get("choices", [])
            content = choices[0].get("message", {}).get("content", "") if choices else ""
            return self._parse(content)
        except Exception:
            logger.warning(
                "Proportionality judgment failed, defaulting to justified", exc_info=True
            )
            return ProportionalityVerdict(justified=True, reason="judgment_failed")

    def _build_prompt(self, shape: ProposedDagShape) -> list[dict[str, str]]:
        user = (
            f"Objective: {shape.objective}\n"
            f"Proposed nodes: {list(shape.node_kinds)}\n"
            f"Synthesizer's rationale: {shape.rationale}\n"
            f"Estimated cost: {shape.estimated_cost}"
        )
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]

    def _parse(self, text: str) -> ProportionalityVerdict:
        cleaned = text.strip()
        m = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(1).strip()
        try:
            data: dict[str, Any] = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            return ProportionalityVerdict(justified=True, reason="unparseable_judgment")

        return ProportionalityVerdict(
            justified=bool(data.get("justified", True)),
            add=tuple(data.get("add") or ()),
            drop=tuple(data.get("drop") or ()),
            reason=str(data.get("reason") or ""),
        )
