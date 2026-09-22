---
inventory-delta:
  packages/maistro-core/tests: +6
  packages/hive-conductor/backend/tests: +2
  tests/: +1
---

# Diff-coverage closers for the #446 CI coverage gate (#446 repair)

The CI run at 86d95fd9
(<https://github.com/Agent-StrongHold/Project-mAIstro/actions/runs/35756123462/job/106844336760>)
failed the quality gate "Coverage gate (publish-set floor + diff coverage)"
with 4 files below the per-file diff-coverage floor. The repair closes each
with real execution, not exemptions:

- `packages/hive-conductor/backend/services/dag_run_inspection.py` (82.6% ->
  floor): every uncovered changed line was a canonical-spine-CONFIGURED
  branch. New `test_dag_run_canonical_reads.py` (+2) pins the serving side of
  the configured spine: the canonical listing (scope-filtered, newest-first),
  the detail record built from a projection row overlaid with canonical
  lifecycle, the by-id/batch answers, and the refusal for a canonical id the
  store never saw.
- `packages/maistro-core/src/maistro/builders/session_composition.py` (0% ->
  floor): the shipped session composition was executed only by
  `tests/cross_product_parity`, which runs under the quality gate's `scripts`
  producer and never reaches the maistro-core measurement. New
  `packages/maistro-core/tests/builders/test_session_composition.py` (+4)
  pins dispatcher adaptation, spine wiring, and a completed and a failed turn
  on the durable spine — read back through the stores the pipeline was handed.
- `packages/maistro-core/src/maistro/cli/_builders_tui.py` (0% -> floor): the
  TUI could not even be imported by the measuring environment — `textual`
  ships in `maistro-core[builders]`, a member extra that root `uv sync
  --all-extras` does not pull (the s3/google-re2 trap, in the gate's own
  words). New root passthrough extra `builders` makes the module importable
  in CI, and new `packages/maistro-core/tests/cli/test_builders_tui.py` (+2)
  boots the real Textual app headlessly and drives one successful and one
  failed turn, asserting both the chat surface and the canonical Run evidence
  in the turn's SQLite database. Only the model-call boundary (TurnRunner) is
  a deterministic fake.
- `scripts/check-vulture-baseline.py` (85.7% -> floor): the
  `_default_scan_args` no-roots guard (new in the previous #446 repair)
  shipped unexercised. New test in `tests/test_check_vulture_baseline.py`
  (+1) asserts the loud SystemExit refusal.

Also: `session_composition.TurnDispatcher` now translates agent-loop
exceptions into the `DispatchResult(ok=False, error=...)` contract instead of
propagating them raw — previously a failing model call left
`failed_stage_error` empty and the TUI printed "Builder run failed:" with no
reason. The failure surfaces as a failed canonical Run with a named error.
