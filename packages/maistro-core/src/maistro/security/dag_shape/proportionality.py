"""Proportionality judge — the "need" axis of DAG shape review.

Neither Warden (threat detection) nor Sentinel (policy/budget authorization)
answers "is this decomposition actually proportional to the objective."
That's a reasoning call, not a policy or safety call, so it gets its own
lightweight critic — same cost/latency shape as Warden's L3 classifier
(cheap model, few-shot, ~100-200ms), scoring proportionality instead of
threat.

Advisory status and failure policy (#1191)
-----------------------------------------

This layer is ADVISORY. Warden and Sentinel are the hard gates and execute
ahead of it; a proportionality outcome can never grant what they denied, and
its unavailability must not be promoted into a new hard availability
dependency. The failure policy is:

- A judgment is returned as disposition ``allow`` (justified) or ``deny``
  (not justified) — both are real judgments.
- Anything that prevents a judgment — model timeout, provider exception,
  malformed response envelope, unparseable or schema-violating JSON — is
  disposition ``unavailable`` with ``justified=False``. It is NEVER
  collapsed into ordinary allow evidence: ``justified=False`` fails safe for
  callers that only look at the boolean, and the disposition names the
  failure for callers that implement the degraded-allow product policy
  (see `evaluate_dag_shape`, which proceeds with ``approved_degraded``).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from maistro.security.dag_shape.types import (
    ProportionalityDisposition,
    ProposedDagShape,
)

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
    """The critic's outcome, split from the judgment itself.

    ``justified`` answers "is this shape proportional" and is only True when
    the judge actually said so. ``disposition`` says what produced the
    verdict: ``allow``/``deny`` are judgments; ``unavailable`` means no
    judgment exists (judge failed, timed out, or answered malformed) and
    never counts as affirmative approval evidence (#1191).
    """

    justified: bool
    disposition: ProportionalityDisposition = "allow"
    add: tuple[str, ...] = field(default_factory=tuple)
    drop: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""

    @classmethod
    def unavailable(cls, reason: str) -> ProportionalityVerdict:
        """The judge could not be consulted or could not answer coherently.

        ``justified=False`` so a caller checking only the boolean fails safe;
        ``disposition="unavailable"`` so a caller implementing the degraded
        policy can tell this apart from an actual denial.
        """
        return cls(justified=False, disposition="unavailable", reason=reason)


@runtime_checkable
class ProportionalityJudge(Protocol):
    async def judge(self, shape: ProposedDagShape) -> ProportionalityVerdict: ...


class RuleProportionalityJudge:
    """Deterministic fallback: always justified. Used in tests and when no LLM is wired.

    This is an explicit configuration state, not a failure: disposition is a
    real ``allow`` because the deployment chose to run with no LLM critic.
    An LLM judge that FAILS reports ``unavailable`` instead (#1191).
    """

    async def judge(self, shape: ProposedDagShape) -> ProportionalityVerdict:
        return ProportionalityVerdict(
            justified=True, disposition="allow", reason="no LLM judge configured"
        )


class LLMProportionalityJudge:
    """Real critic: asks a cheap model whether the shape is proportional.

    Failures (timeout, provider error, malformed reply) produce an
    ``unavailable`` verdict — never a silent affirmative allow (#1191).
    Whether to proceed despite an unavailable advisory judge is the caller's
    documented degraded policy, not something this class decides.
    """

    def __init__(self, llm: LLMClient, model: str = "auto") -> None:
        self._llm = llm
        self._model = model

    async def judge(self, shape: ProposedDagShape) -> ProportionalityVerdict:
        try:
            messages = self._build_prompt(shape)
            response = await self._llm.complete(messages, self._model)
        except Exception as exc:
            # Advisory judge unavailable. Recorded as an explicit disposition,
            # never defaulted to a proportionality approval: this warning is
            # the metrics signal that the advisory layer is down.
            logger.warning(
                "proportionality_judge_unavailable: llm call failed",
                exc_info=True,
                extra={"stage": "llm_call", "error_type": type(exc).__name__},
            )
            return ProportionalityVerdict.unavailable(
                f"judge_unavailable: llm call failed ({type(exc).__name__})"
            )
        content = self._extract_content(response)
        if content is None:
            logger.warning(
                "proportionality_judge_unavailable: malformed response envelope",
                extra={"stage": "response_shape"},
            )
            return ProportionalityVerdict.unavailable(
                "judge_unavailable: malformed response envelope"
            )
        return self._parse(content)

    @staticmethod
    def _extract_content(response: Any) -> str | None:
        """The completion text, or None when the envelope is not the expected
        shape — an absent/odd answer is an unavailable judge, not an allow."""
        if not isinstance(response, dict):
            return None
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        first = choices[0]
        if not isinstance(first, dict):
            return None
        message = first.get("message")
        if not isinstance(message, dict):
            return None
        content = message.get("content")
        return content if isinstance(content, str) else None

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
            data: Any = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            return ProportionalityVerdict.unavailable(
                "judge_unavailable: malformed judgment (not valid JSON)"
            )
        # A reply without an explicit boolean verdict did not judge anything;
        # defaulting the missing key to True would be a silent allow (#1191).
        if not isinstance(data, dict) or not isinstance(data.get("justified"), bool):
            return ProportionalityVerdict.unavailable(
                "judge_unavailable: malformed judgment (missing boolean 'justified')"
            )

        justified = data["justified"]
        return ProportionalityVerdict(
            justified=justified,
            disposition="allow" if justified else "deny",
            add=_string_tuple(data.get("add")),
            drop=_string_tuple(data.get("drop")),
            reason=str(data.get("reason") or ""),
        )


def _string_tuple(value: Any) -> tuple[str, ...]:
    """Normalize the add/drop lists, tolerating a model that omits them or
    sends a non-list; a non-list is treated as empty rather than raising out
    of parsing (the boolean verdict above is still honoured)."""
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value)
