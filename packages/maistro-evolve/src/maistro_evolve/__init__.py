"""maistro-evolve: Elo tournament optimizer for agent self-improvement.

Behavior inventory (SPEC-202 / v1 release plan D3, #291): this package ships
a genome-evolution pipeline (crossover, mutation, tournament selection,
fitness scoring) that runs against seven named benchmarks — ``ifeval``,
``bfcl``, ``swebench``, ``tau_bench``, ``gaia``, ``ragas``, ``terminalbench``
(``osworld`` is defined but not runnable; it has no scoring implementation).
None of the seven run the official published benchmark harness against the
official dataset — all score real model output at a small, handcrafted
scale. Fidelity within that scale is NOT uniform: only ``swebench``/
``terminalbench`` (real sandboxed execution) and ``ifeval`` (real
per-instruction rule checks) are cleanly structural. ``bfcl``, ``gaia``, and
``tau_bench`` each carry a real text-mention or fuzzy-substring fallback
that materially weakens their fidelity; ``ragas`` is primarily a
keyword-overlap heuristic. Full per-benchmark detail — including the exact
degenerate cases — lives in this package's ``CLAUDE.md``; do not trust this
paragraph's summary over that detail.

**Governance note, not resolved here:** ``docs/adr/ADR-088-maistro-evolve-experimental.md``
is Accepted and states this package "is EXPERIMENTAL... has no stability
contract... No other package should depend on its API surface as if it were
locked." This inventory exists because the v1 release plan (#277) directs
evolve/RSI to ship as v1 features with a stated contract (D3/#291) — but
that direction does not by itself supersede an Accepted ADR. Read this as
the D3-directed behavior inventory the release plan asked for, not a claim
that overrides ADR-088; reconciling the two (amend or supersede ADR-088, or
narrow what "stability" means here) needs an explicit human decision, not a
silent one made in a docstring.
"""

from __future__ import annotations

import importlib.metadata

# Single source of truth for version — read from installed package metadata.
try:
    __version__ = importlib.metadata.version("maistro-evolve")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - editable/unbuilt checkout
    __version__ = "0.9.0-dev"
