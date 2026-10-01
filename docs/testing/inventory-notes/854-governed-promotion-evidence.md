---
inventory-delta:
  packages/maistro-evolve/tests: +17
---

# Governed champion selection and promotion evidence (#854)

Adds the behavioral proof suite for #21's one canonical
candidate → independent evaluation → governed promotion contract
(`packages/maistro-evolve/src/maistro_evolve/promotion.py`), exercised through
the real `PopulationStore`/`EvolutionCycle` surfaces:

- a lucky single sample is refused by champion selection and promotion
  (insufficient independent evidence, `min_samples_per_benchmark`);
- best-of-N winners stay promotion-ineligible until a fresh post-acceptance
  sample (winner's-curse guard) and unstable sample spread fails the
  uncertainty bound;
- unevaluated offspring are excluded from selection/promotion and are not
  culled for lacking a score;
- gate-failed, stale (`max_evidence_age_cycles`), objective-mismatched, and
  unapproved candidates are excluded at the right gate (approval binds
  promotion, not selection);
- a worse candidate cannot replace a stronger incumbent by calling
  `promote()` later (`min_promotion_margin` under one immutable objective
  version); a genuinely better, independently confirmed candidate promotes
  with a complete decision record;
- the production cycle re-samples already-evaluated genomes
  (`reconfirm_per_cycle`), so the declared EMA estimator actually runs through
  the real cycle instead of a first sample being permanent.

Existing champion/promotion tests were moved onto the governed contract
(evidence stamps + margin), including the formal audit-trail conformance
models, which now drive successive strictly-better promotions so the #342
audit properties keep exercising real transitions; rejections are audited as
`promotion_attempt` + `promotion_rejected` with reasons.

## Repair-round record (develop sync + gate validation)

The prior round left a half-applied index-only rebuild ("corrupt patch at
line 525344") that held the `origin/develop` tree staged while the worktree
stayed at HEAD; the index content was verified byte-identical to
`origin/develop` (`git diff --cached origin/develop` empty), backed up to the
job's salvage directory, then unstaged with a mixed reset (worktree untouched)
so the sync could be redone properly. `origin/develop` (fa2deb0a4, 28 commits)
was merged cleanly (merge commit f63a493f5); the only both-sides-touched file,
`quality/vulture-baseline.json`, auto-merged — both sides' eliminated
identities are absent. No #854 surface was touched by develop.

Post-merge validation on the merged tree:

- coverage producers exactly as `quality.yml` `coverage (no services)` runs
  them: core 10944 passed, evolve 733 passed, canvas 426 passed, rsi 786
  passed, bootstrap 233 passed. The one core failure in the local full-suite
  run (`test_an_unreachable_server_is_an_error_not_a_fallback`) is a WSL
  environment artifact — connecting to 127.0.0.1:1 hangs ~60s under mirrored
  networking instead of failing fast, tripping the suite's `--timeout=30`;
  the test passes in isolation locally and passes in CI where the refusal is
  immediate (develop CI green at fa2deb0a4 for the same producer). The
  originally reported CI failure
  (`test_parked_run_resume.py::..._reclaimed_after_worker_death[sqlite]`, a
  heartbeat-timing test this branch never touched) passes locally and is
  covered by develop's green runs.
- `ruff check` / `ruff format --check` / evolve suite inventory: green.
- vulture per-identity ledger gate (`check-vulture-baseline.py`, min
  confidence 60): unclassified 0, never_allowlist 0, ratchet green.
- formal audit-trail/rollback conformance + the driver's five evolve test
  files: 118 passed. mypy over core/server/turing/canvas/bootstrap/registry:
  clean (737 files).
