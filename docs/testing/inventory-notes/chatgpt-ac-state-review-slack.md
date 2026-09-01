---
inventory-delta:
  tests/: +10
---

# AC-state review-time no-rebank policy

Adds ten focused root-suite cases for the branch-independence transition:

- canonical `develop` PR CI may treat safe measurement improvement as informational;
- imported or synthetic PR execution retains conservative banking;
- direct-front-door detection fails closed when path resolution is unavailable;
- candidate note folds must contain every bounded counter;
- candidate note folds are compared against the trusted fold after reviewed floor authorizations;
- candidate note-fold weakening is never excused as measurement slack;
- merge-group handling still delegates to the existing merge policy after note validation;
- relaxed success wording says counters satisfy their bounds rather than claiming exact equality;
- relaxed output is captured and rewritten consistently; and
- the public ratchet installs and restores the implementation hook for each invocation.

The merge/protected-branch actual-base guard remains the authoritative
monotonicity check. Regressions still fail; an improvement observed on the
proven queued `develop` review path no longer requires a bookkeeping commit
merely to mirror a moving or run-variable measurement.