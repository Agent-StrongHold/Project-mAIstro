---
inventory-delta:
  tests/: +6
---

# AC-state review-time no-rebank policy

Adds six focused root-suite cases for the branch-independence transition:

- canonical `develop` PR CI may treat safe measurement improvement as informational;
- imported or synthetic PR execution retains conservative banking;
- candidate note-fold weakening is never excused as measurement slack;
- merge-group handling still delegates to the existing merge policy after note validation;
- successful relaxed output says the counters satisfy their bounds rather than claiming exact equality; and
- the public ratchet restores the implementation hook after each invocation.

The merge/protected-branch actual-base guard remains the authoritative
monotonicity check. Regressions still fail; an improvement observed on the
proven queued `develop` review path no longer requires a bookkeeping commit
merely to mirror a moving or run-variable measurement.