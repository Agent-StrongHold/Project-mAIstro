"""Cage verdicts: deterministic gates that return answers instead of raising.

Ported in shape from the Turing cage (hive-conductor ``cage/turing_cage.py``):
every checkpoint is deterministic, every check returns a structured verdict,
and a blocked verdict halts the action — but never by exception. An automaton
whose cage can throw has a hole in its cage that opens exactly when things go
wrong, which is the only time the cage is interesting.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from maistro_automaton.types import Candidate


@dataclass(frozen=True)
class CageVerdict:
    """The only way a checkpoint says anything: structured, or not at all.

    ``reason_code`` must be a stable, enumerated string a ticket system can
    group on (``"REFRACTORY"``, ``"OWNER_GATED"``, ``"IMMUTABLE_PATH"``) —
    raw exception text is not a reason code, it is an archaeology project.
    """

    blocked: bool
    reason_code: str
    checkpoint: str
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def allow(cls, checkpoint: str) -> CageVerdict:
        return cls(blocked=False, reason_code="ALLOWED", checkpoint=checkpoint)

    @classmethod
    def block(cls, checkpoint: str, reason_code: str, **details: Any) -> CageVerdict:
        return cls(
            blocked=True,
            reason_code=reason_code,
            checkpoint=checkpoint,
            details=dict(details),
        )


@runtime_checkable
class CageCheckpoint(Protocol):
    """A deterministic gate over one candidate. Name it; verdicts cite it."""

    checkpoint: str

    def check(self, candidate: Candidate) -> CageVerdict: ...


def first_block(checkpoints: Iterable[CageCheckpoint], candidate: Candidate) -> CageVerdict:
    """Run candidate through every checkpoint; first block wins, else allow.

    Checkpoints run in order — cheap and structural gates (refractory,
    ownership) before expensive ones. Deterministic order, deterministic
    winner: the first blocking verdict is THE reason the action did not run,
    and it is the reason code that lands in the episode log.
    """
    for checkpoint in checkpoints:
        verdict = checkpoint.check(candidate)
        if verdict.blocked:
            return verdict
    return CageVerdict.allow(checkpoint="all")
