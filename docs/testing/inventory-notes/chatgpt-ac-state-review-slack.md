---
inventory-delta:
  tests/: +3
---

# AC-state review-time no-rebank policy

Adds three focused root-suite cases for the branch-independence transition:
pull-request improvements are informational rather than a mandatory bank,
merge-group handling still delegates to the existing merge policy, and the
front-door ratchet restores the implementation hook after each invocation.

The merge/protected-branch actual-base guard remains the authoritative
monotonicity check. Regressions still fail; an improvement observed during
review no longer requires a bookkeeping commit merely to mirror a moving or
run-variable measurement.
