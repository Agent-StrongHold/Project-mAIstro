"""Independent Gauntlet validation before collective promotion (M4-B #118).

A learning crosses into the collective repertoire only after a Gauntlet that
did not produce it, and does not trust its producer's enthusiasm, accepts the
outcome evidence later Runs recorded. Deliberately absent from the evidence:
``hit_count``. Recall frequency measures how often a learning was *injected*,
not whether following it helped -- a learning recalled constantly and followed
by failures must fail the Gauntlet, which is exactly the case a hit-count
threshold alone would wave through.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from maistro.types.memory import Learning


@dataclass(frozen=True)
class GauntletEvidence:
    """What a Gauntlet judges: recorded outcomes of later Runs, nothing else."""

    #: Times the learning was injected into a later Run **and** an outcome came
    #: back -- the only sample whose verdict the Gauntlet can read.
    uses: int = 0
    successes: int = 0
    failures: int = 0
    contradictions: int = 0
    reinforcements: int = 0
    #: The Run that produced the learning (ADR-083026-e602). Unattributed
    #: knowledge cannot be validated, because nothing can be checked against
    #: the execution that taught it.
    producer_run_id: str = ""


def evidence_of(learning: Learning) -> GauntletEvidence:
    """Build the Gauntlet's view of a learning from its recorded outcomes.

    The projection is deliberately narrow: no hit_count, no trigger keys, no
    producer claims -- only what later Runs actually did after the learning
    was applied.
    """
    return GauntletEvidence(
        uses=learning.success_after_use + learning.failure_after_use,
        successes=learning.success_after_use,
        failures=learning.failure_after_use,
        contradictions=learning.contradiction_count,
        reinforcements=learning.reinforcement_count,
        producer_run_id=learning.run_id,
    )


@dataclass(frozen=True)
class GauntletVerdict:
    """A Gauntlet's decision, with the checks it failed when it says no."""

    ok: bool
    reason: str = ""
    gauntlet: str = ""
    failed_checks: tuple[str, ...] = ()


@runtime_checkable
class LearningGauntlet(Protocol):
    """An independent validator standing between learning and repertoire."""

    name: str

    async def evaluate(self, learning: Learning, *, evidence: GauntletEvidence) -> GauntletVerdict:
        """Judge the recorded evidence; return the verdict."""
        ...


class OutcomeEvidenceGauntlet:
    """Judges recorded outcome evidence against declared thresholds.

    Independent by construction: it reads only the :class:`GauntletEvidence`
    projection and the learning's current confidence, never its hit count or
    its producer's identity beyond whether one exists at all.
    """

    def __init__(
        self,
        *,
        name: str = "outcome-evidence",
        min_uses: int = 3,
        min_success_rate: float = 0.6,
        max_contradiction_excess: int = 0,
        min_confidence: float = 0.4,
        require_producer: bool = True,
    ) -> None:
        self.name = name
        self._min_uses = min_uses
        self._min_success_rate = min_success_rate
        self._max_contradiction_excess = max_contradiction_excess
        self._min_confidence = min_confidence
        self._require_producer = require_producer

    async def evaluate(self, learning: Learning, *, evidence: GauntletEvidence) -> GauntletVerdict:
        """Apply every check; one verdict names all failed checks."""
        failed: list[str] = []
        if evidence.uses < self._min_uses:
            failed.append("min_uses")
        if evidence.uses > 0 and evidence.successes / evidence.uses < self._min_success_rate:
            failed.append("success_rate")
        if evidence.contradictions - evidence.reinforcements > self._max_contradiction_excess:
            failed.append("contradictions")
        if learning.confidence < self._min_confidence:
            failed.append("confidence")
        if self._require_producer and not evidence.producer_run_id:
            failed.append("producer")

        if failed:
            return GauntletVerdict(
                ok=False,
                reason=f"failed: {', '.join(failed)}",
                gauntlet=self.name,
                failed_checks=tuple(failed),
            )
        return GauntletVerdict(
            ok=True,
            reason=(
                f"{evidence.successes}/{evidence.uses} uses succeeded, "
                f"{evidence.contradictions} contradictions"
            ),
            gauntlet=self.name,
        )


class ChainedGauntlet:
    """Compose gauntlets: all must accept, failures are reported as the union."""

    def __init__(self, *members: LearningGauntlet, name: str = "gauntlet-chain") -> None:
        if not members:
            raise ValueError("a ChainedGauntlet needs at least one member gauntlet")
        self.name = name
        self._members = members

    async def evaluate(self, learning: Learning, *, evidence: GauntletEvidence) -> GauntletVerdict:
        """Run every member; the chain passes only when each member passes."""
        failed: list[str] = []
        reasons: list[str] = []
        for member in self._members:
            verdict = await member.evaluate(learning, evidence=evidence)
            if not verdict.ok:
                failed.extend(verdict.failed_checks or (member.name,))
                reasons.append(f"{member.name}: {verdict.reason}")
        if failed:
            return GauntletVerdict(
                ok=False,
                reason="; ".join(reasons),
                gauntlet=self.name,
                failed_checks=tuple(failed),
            )
        return GauntletVerdict(ok=True, gauntlet=self.name)
