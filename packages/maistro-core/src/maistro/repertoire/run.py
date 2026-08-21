"""The reuse-first cascade core (SPEC-258 / ADR-070)."""

from __future__ import annotations

from typing import TypeVar

from maistro.repertoire.protocol import Repertoire
from maistro.repertoire.types import PerformGate, RehearsalFailed

InputT = TypeVar("InputT")
S = TypeVar("S")
E = TypeVar("E")


async def repertoire_run(
    rep: Repertoire[InputT, S, E], inp: InputT, *, stakes: float, gate: PerformGate
) -> S:
    """Recall -> gate -> improvise -> rehearse -> compose, returning the resulting solution."""
    input_class = rep.class_of(inp)
    entry = rep.recall(input_class)
    if entry is not None and gate.should_perform(entry, stakes=stakes):
        return entry  # type: ignore[return-value]

    priors = rep.nearest(input_class)
    candidate = rep.improvise(inp, priors)

    verdict = rep.rehearse(candidate)
    if not verdict.ok:
        raise RehearsalFailed(verdict)

    rep.compose(candidate, input_class)
    return candidate
