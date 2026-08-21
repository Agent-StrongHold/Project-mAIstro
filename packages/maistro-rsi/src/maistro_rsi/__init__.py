"""maistro-rsi — recursive self-improvement on the agent's own codebase.

Wires together three things that already exist in the monorepo:

- An isolated execution environment (`maistro_rsi.sandbox`), abstracted behind
  the `MicroVmSandbox` protocol so the eventual backend (Firecracker, E2B,
  gVisor — ADR pending) is a swap-in, not a rewrite.
- The self-branch workflow (`maistro_rsi.selfbranch`), which reuses
  `maistro.tools.git` to clone, branch, patch, test, and propose changes to
  this very repository from inside a sandbox.
- The benchmark/tournament/fitness stack from `maistro_evolve` — extended
  here with longer-horizon adapters (e.g. SWE-Bench Pro) — to record whether a
  self-modification is an improvement, via Elo battles against a baseline.

`maistro_rsi.quota_burn` adds a scheduler that spreads cycles across whatever
models the connected LiteLLM instance exposes, favoring the ones with the
most idle free-tier headroom so unused allowances get exercised.

Behavior inventory (SPEC-202 / v1 release plan D3, #291): **benchmark
scoring does not gate PR creation.** `RsiCycle.run()` (`runner.py`) calls
`run_self_branch_attempt(..., open_pr=self._config.open_prs, ...)` — which
opens the PR if `open_prs=True`, gated only by `quarantine_check` — strictly
*before* `self._score(...)` runs the benchmark/tournament comparison against
baseline. A candidate that passes quarantine but loses every benchmark can
already be a public PR by the time that loss is recorded. Quarantine is the
real gate on whether a PR opens at all; benchmark/tournament scoring feeds
Elo/promotion tracking after the fact, not PR creation.

Fitness scoring inherits `maistro_evolve`'s proxy-tier benchmarks (see that
package's docstring and `CLAUDE.md` for exactly how reliable each one is —
several have real heuristic fallbacks, not just `ragas`) plus this package's
own `swebench_pro` adapter, which ships a small embedded sample set "in the
spirit of" the real SWE-Bench Pro corpus (arXiv:2509.16941) rather than the
full held-out split. Unlike every `maistro_evolve` scorer, `swebench_pro`
falls back to a candidate-independent *random* score when no model is
available (`_heuristic_score`, `random.uniform`) rather than raising — a
deliberate choice so the autorun loop degrades instead of halting when
idle-quota headroom is exhausted. That fallback result carries
`metadata["stub"] = True`, `maistro_evolve`'s established noise flag, so
`reflective_improve`/`hyper_mutate` refuse to treat it as real signal.

Best-effort, not guaranteed: specific sample sets, sandbox backend choice
(ADR pending), and which model rosters are exercised in CI.

**Governance note, not resolved here:** this inventory exists because the v1
release plan (#277) directs evolve/RSI to ship as v1 features with a stated
contract (D3/#291). `maistro_evolve`'s own governing ADR-088 is Accepted and
states that package has "no stability contract" and should not be depended
on "as if it were locked" — a newer, more detailed but still-`Proposed`
architecture doc (`ADR-070126-6386-rsi-evolve-genome-tournament.md`)
describes this package's actual production cycle far more precisely than
the summary above, but doesn't supersede ADR-088 either. Read this
docstring as the D3-directed behavior inventory, not a claim that resolves
that governance gap — reconciling it needs a human decision.
"""

from __future__ import annotations

import importlib.metadata
from typing import Any

# Single source of truth for version — read from installed package metadata.
try:
    __version__ = importlib.metadata.version("maistro-rsi")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - editable/unbuilt checkout
    __version__ = "0.9.0-dev"

from maistro_rsi.coordinator import (
    CoordinatorResult,
    ExecutionReport,
    ExecutorFn,
    HtrContext,
    HtrCoordinator,
    HypothesisProposer,
    report_from_cycle_result,
)
from maistro_rsi.htr import (
    HypothesisEvidence,
    HypothesisNode,
    HypothesisTree,
    NodeStatus,
)
from maistro_rsi.protocols import ApplyPatchFn, MicroVmSandbox

__all__ = [
    "ApplyPatchFn",
    "CoordinatorResult",
    "ExecutionReport",
    "ExecutorFn",
    "HtrContext",
    "HtrCoordinator",
    "HypothesisEvidence",
    "HypothesisNode",
    "HypothesisProposer",
    "HypothesisTree",
    "MicroVmSandbox",
    "NodeStatus",
    "RsiCycle",
    "RsiCycleConfig",
    "RsiCycleResult",
    "__version__",
    "report_from_cycle_result",
]


def __getattr__(name: str) -> Any:
    """Lazy-load runner exports to avoid pulling in sandbox chain for
    coordinator-only imports."""
    if name in ("RsiCycle", "RsiCycleConfig", "RsiCycleResult"):
        from maistro_rsi import runner

        return getattr(runner, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
