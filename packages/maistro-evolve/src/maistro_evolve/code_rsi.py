"""The ``code_rsi`` benchmark: score a genome by the code fix it produces.

Implements ADR-070126-6386 / SPEC-070126-9d37. A genome's ``code_rsi`` score is
the composite of the RSI ``Scorecard`` for the fix that genome's config produced,
with two invariants borrowed from the rest of evolve:

  - **Hard-gate parity.** A vetoed gate collapses the score to 0, regardless of
    how high the weighted composite was (mirrors ``FitnessComponents`` gates).
  - **Honesty (SPEC-202).** Never score against a stubbed/absent test suite; a
    stub signal scores 0 and is flagged, so a genome can't "win" against noise.

The actual agent run + scorecard live in ``maistro_rsi`` (this package must not
depend on it), so callers inject ``run_and_score``; this module only maps its
outcome onto an ``EvalResult`` the harness/tournament understands.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from maistro_evolve.types import EvalResult

RunAndScore = Callable[[Any, str], "tuple[bool, float, bool]"]


def code_rsi_score(
    *, accepted: bool, composite: float, is_stub: bool = False
) -> tuple[float, dict[str, Any]]:
    """Map an RSI scorecard outcome to a ``(score, metadata)`` for ``code_rsi``."""
    if is_stub:
        return 0.0, {"stub": True}
    return (composite if accepted else 0.0), {"accepted": accepted}


def evaluate_code_rsi(genome: Any, target: str, run_and_score: RunAndScore) -> EvalResult:
    """Run ``run_and_score(genome, target) -> (accepted, composite, is_stub)`` and
    wrap the mapped score as a ``code_rsi`` ``EvalResult``."""
    accepted, composite, is_stub = run_and_score(genome, target)
    score, meta = code_rsi_score(accepted=accepted, composite=composite, is_stub=is_stub)
    return EvalResult(benchmark="code_rsi", score=score, metadata=meta)
