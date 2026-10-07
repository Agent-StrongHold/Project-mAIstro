---
inventory-delta:
  tests/: +27
---
# 884 execution-lease model checker

Implements the #884 (RESEARCH M8-A4) deliverable: an exhaustive bounded model
checker for the consumer-claim execution spine (claim → dispatch → commit →
accept → cancel → crash → recover → retry), plus the TLA+/TLC rendering of the
same transition relation under
`docs/research/models/884-execution-lease/`. The research record and the
GRADUATE/INCUBATE/REJECT/WATCH disposition (INCUBATE) are in
`docs/research/884-tla-plus-model-checking-execution-concurrency.md`. No
product code changes.

All additions, no removals:

- `scripts/model_check_consumer_claim.py` — the checker (measured root:
  `scripts/` is the coverage producer's source, and this file sits at 99%
  line coverage under `tests/test_model_check_consumer_claim.py`; the only
  uncovered statement is the `if __name__` guard).
- `tests/test_model_check_consumer_claim.py` — **+27 tests** in the root
  `tests/` suite: model-vs-shipped conformance (every modeled Run/Attempt
  move is legal per the *imported* `maistro.runs.lifecycle` tables; the
  lease-expiry predicate derives time identically to the shipped
  `lease_is_expired`, cross-checked over unexpired/lapsed/terminal/
  lease-less Attempts built from the real pydantic models); the guarded
  protocol exhaustively clean (9,520 states, zero violations, no deadlock
  beyond the declared ceilings, progress without a person under the stated
  fairness); the unguarded protocol violating exactly S3+S4 with traces that
  are the shipped races (ADR-082426-e3ff's stale acceptance; #1335's cancel
  landing inside the begin/land commit window); effect-once holding exactly
  under `once` semantics with the `retryable` re-dispatch riding recovery;
  the can-fail discipline (#410) — every invariant demonstrated to fire
  against a realistic mutant (resume over a live owner, dropped
  ReplayRefused, acceptance over a terminal Run, a store dropping the
  Attempt transition-table guard, a clockless world for the stuck-state
  detector); named-window behavior (landing refused after reclamation,
  guarded conversion vs unguarded COMPLETED-under-CANCELLED, fenced
  acceptance refusing a superseded holder); determinism of exploration;
  CLI JSON/human output and exit codes; and `Spec` bound validation.

Everything is offline, stdlib-only and deterministic (seedless by
construction: exhaustive BFS in a fixed action order), with the full
both-variant exploration ~2 s, respecting the root suite's `--timeout=30`
producer budget.
