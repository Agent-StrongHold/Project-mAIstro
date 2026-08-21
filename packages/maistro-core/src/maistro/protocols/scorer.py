"""Scorer protocol — pluggable eval providers (ADR-060)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Score:
    """Result from any Scorer provider."""

    value: float  # 0.0-1.0
    passed: bool
    rationale: str
    evidence: list[str] = field(default_factory=list)  # source URLs or criterion names
    provider: str = "unknown"  # "rubric" | "deepeval" | "promptfoo" | ...
    details: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Scorer(Protocol):
    """Evaluate one output against one eval dimension.

    All providers must implement this method.  The contract:
    - ``output``: the text to score.
    - ``context``: optional domain hints (brand keywords, competitor list, …).
    - Returns a ``Score`` with value in [0, 1].
    - Never raises on bad input — return a Score with value=0 and a
      rationale explaining what went wrong.
    """

    async def score(self, output: str, context: dict[str, Any] | None = None) -> Score: ...
