"""Cheap-first, quality-triggered model escalation (epic M4-I).

A Run that needs a strong model for every step pays strong-model prices for
easy steps, and a Run that uses a cheap model for everything silently ships
low-quality work. The middle path is a ladder: run the cheapest rung first,
supervise the result's quality, and spend the next rung only when the gate
says the current one was not good enough.

The ladder is declared on the node — ``policies["escalation_ladder"]`` — so
it rides the immutable Graph snapshot like every other execution contract,
and the executor's supervision (the authoritative fold) consumes it: a
completed visit whose self-reported ``quality`` metadata misses the floor is
*withheld* from advancement and re-queued as a fresh visit whose
``NodeContext.metadata["escalated_model"]`` names the next rung. The
physical Attempt that already ran is never rewritten — escalation is a new
visit under a new NodeRun, exactly like the retry contract it shares the
visit budget with.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: NodeResult metadata key carrying the node's self-reported quality (0..1).
QUALITY_METADATA_KEY = "quality"
#: Node policy key carrying the escalation ladder declaration.
ESCALATION_LADDER_POLICY_KEY = "escalation_ladder"
#: GraphExecutionState metadata key recording per-node escalation progress.
ESCALATION_STATE_METADATA_KEY = "escalations"
#: NodeContext metadata key through which the executor hands the re-visit its rung.
ESCALATED_MODEL_CONTEXT_KEY = "escalated_model"
#: NodeContext metadata key through which the executor seeds a declared
#: ladder's cheapest rung for a node's *first* supervised visit, so
#: cheap-first starts the ladder rather than the node's ambient default
#: model. Distinct from ``escalated_model``: a seeded start is the ladder's
#: own beginning, so node-level rules that outrank it (an image
#: observation's vision alias, say) still apply, while a supervision
#: escalation is final and outranks everything.
LADDER_START_CONTEXT_KEY = "escalation_ladder_start"


class ModelLadder(BaseModel):
    """Ordered model rungs, cheapest first. Position, not price, is the contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    models: tuple[str, ...] = Field(min_length=1)

    @field_validator("models")
    @classmethod
    def _validate_models(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not model.strip() for model in value):
            raise ValueError("model ladder rungs must be non-empty strings")
        if len(set(value)) != len(value):
            raise ValueError("model ladder rungs must be unique")
        return value

    @property
    def cheapest(self) -> str:
        return self.models[0]

    @property
    def strongest(self) -> str:
        return self.models[-1]

    def index_of(self, model: str) -> int | None:
        """Position of ``model`` on the ladder, or ``None`` when it is not a rung."""
        try:
            return self.models.index(model)
        except ValueError:
            return None

    def next_after(self, model: str) -> str | None:
        """The next stronger rung, or ``None`` when ``model`` is already strongest (or not a rung)."""
        index = self.index_of(model)
        if index is None or index + 1 >= len(self.models):
            return None
        return self.models[index + 1]


class QualityGate(BaseModel):
    """Minimum acceptable self-reported quality. Below the floor fails the gate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    floor: float = Field(ge=0.0, le=1.0)

    def passes(self, quality: float) -> bool:
        return quality >= self.floor


class EscalationDecision(BaseModel):
    """One supervision decision about a completed visit's quality."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    escalate: bool
    quality: float
    from_model: str | None = None
    to_model: str | None = None
    reason: str

    @property
    def exhausted(self) -> bool:
        """Whether the gate failed and no stronger rung exists to spend."""
        return not self.escalate and self.reason == "ladder exhausted"


def decide_escalation(
    ladder: ModelLadder,
    current_model: str | None,
    quality: float,
    gate: QualityGate,
) -> EscalationDecision:
    """Decide whether a completed visit at ``current_model`` must escalate.

    Cheap-first: the gate failing is necessary but not sufficient — a rung
    is spent only when a stronger rung exists. ``current_model`` of ``None``
    is the first supervised visit: the executor seeds a declared ladder's
    cheapest rung for that visit, so the fold escalates from the cheapest
    rung — the rung that actually ran — not from an ambient default.
    """
    if gate.passes(quality):
        return EscalationDecision(
            escalate=False,
            quality=quality,
            from_model=current_model,
            reason="quality gate passed",
        )
    base = current_model if current_model is not None else ladder.cheapest
    nxt = ladder.next_after(base)
    if nxt is None:
        return EscalationDecision(
            escalate=False,
            quality=quality,
            from_model=current_model,
            reason="ladder exhausted",
        )
    return EscalationDecision(
        escalate=True,
        quality=quality,
        from_model=current_model,
        to_model=nxt,
        reason="quality below floor",
    )


def escalation_from_policy(policies: Mapping[str, Any]) -> tuple[ModelLadder, QualityGate] | None:
    """Read a node's declared escalation ladder and quality gate, or ``None``.

    A malformed declaration raises rather than degrading to "no escalation":
    a ladder nobody can read would otherwise silently accept every shortfall.
    """
    declared = policies.get(ESCALATION_LADDER_POLICY_KEY)
    if declared is None:
        return None
    if not isinstance(declared, Mapping):
        raise ValueError(
            f"node policy {ESCALATION_LADDER_POLICY_KEY!r} must be a mapping, "
            f"got {type(declared).__name__}"
        )
    models = declared.get("models")
    if not isinstance(models, (list, tuple)):
        raise ValueError(
            f"node policy {ESCALATION_LADDER_POLICY_KEY!r} requires a 'models' list "
            f"ordered cheapest first, got {models!r}"
        )
    ladder = ModelLadder.model_validate({"models": list(models)})
    floor = declared.get("quality_floor")
    if not isinstance(floor, (int, float)) or isinstance(floor, bool):
        raise ValueError(
            f"node policy {ESCALATION_LADDER_POLICY_KEY!r} requires a numeric "
            f"'quality_floor' between 0 and 1, got {floor!r}"
        )
    return ladder, QualityGate(floor=float(floor))


__all__ = [
    "ESCALATED_MODEL_CONTEXT_KEY",
    "ESCALATION_LADDER_POLICY_KEY",
    "ESCALATION_STATE_METADATA_KEY",
    "LADDER_START_CONTEXT_KEY",
    "QUALITY_METADATA_KEY",
    "EscalationDecision",
    "ModelLadder",
    "QualityGate",
    "decide_escalation",
    "escalation_from_policy",
]
