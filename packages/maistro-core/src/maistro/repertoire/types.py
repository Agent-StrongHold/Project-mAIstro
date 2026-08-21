"""Repertoire Pattern core types (SPEC-258 / ADR-070)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Verdict:
    """The outcome of a Rehearse step: whether a candidate solution may be composed."""

    ok: bool
    reason: str = ""


class RehearsalFailed(Exception):
    """Raised when a candidate solution fails Rehearse; carries the failing Verdict."""

    def __init__(self, verdict: Verdict) -> None:
        """Store the failing verdict alongside the exception message."""
        super().__init__(verdict.reason or "rehearsal failed")
        self.verdict = verdict


class PerformGate(Protocol):
    """The explore/exploit decision: whether to reuse a recalled entry given the stakes."""

    def should_perform(self, entry: Any, *, stakes: float) -> bool:
        """Return True if the recalled entry should be reused instead of improvising."""
        ...
