---
inventory-delta:
  tests/: +5
---
# ci-split guard-rail coverage for check-required-checks

The granular-checks split (#1357) taught `scripts/check-required-checks.py` to
compose GitHub's reusable-workflow check names (caller name + callee name).
Diff coverage flagged the five `ContractError` refusals in that composed-name
generator as changed-but-never-executed lines, which is exactly the state the
diff gate exists to catch: guard rails that have never fired are guard rails
nobody has proven work.

Five tests drive the real `collect()` entry point over hermetic synthetic
workflow trees, one per refusal: an unresolved `inputs.` reference, an
external (non-local) `uses:`, a callee file that does not exist, a callee with
no jobs, and a callee name carrying a non-input expression the generator
cannot resolve. Each asserts the fail-closed `ContractError` rather than a
silently wrong or silently empty name list. No production lines were added or
removed; the count moves by the five new tests only.
