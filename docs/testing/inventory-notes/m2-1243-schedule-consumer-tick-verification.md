# 1243-schedule-consumer-tick — independent verification

Verified at head `ec39cd6f9dfb03e8c0a5dc2073664c851f8833b5` (aud7; develop base
`78bb7290688a7b404d8d705a47d48c502afdc0a0`), worktree clean, diff under review
= `619a77d2` + merge. All commands below were executed independently.

- Failure-mode regression: `uv run pytest
  packages/hive-conductor/backend/tests/test_schedule_consumer.py -x -q`
  -> 10 passed. The end-to-end test reproduces the audited shape against a
  real Container: `_ScheduleRunner._evaluate_schedule` admits QUEUED, advances
  the cursor, the node never runs, and a later tick is SKIP-suppressed by the
  stranded Run; `tick_schedule_consumer` then drains it to COMPLETED through
  `Container.execute_admitted_runs`.
- Full lane suite: `packages/hive-conductor/backend/tests` -> 2265 passed,
  11 skipped (matches the recorded inventory 2276).
- maistro-core `tests/scheduling` + `tests/runs` -> 858 passed, 180 skipped.
- `ruff check .` and `ruff format --check .` clean.
- Gates exit 0: suite-inventory (all 13 suites and hive-conductor suite),
  wiring-reads, execution-lifecycles, lifecycle-provenance, reachability,
  convergence-matrix, cross-package-imports, radon-baseline.
- Production reachability: `main.lifespan` -> `start_engine` ->
  `EngineService.start` starts the cadence after the bridge bind and
  `start_dag_recovery`; `stop` joins it. Container resolved through the same
  engine AgentPort seam the producer uses (`agent_port` property vs
  `_agent_port` attribute — same object).
- No gate weakening: the diff touches only `config.py` (+9), `engine.py`
  (+11), new `services/schedule_consumer.py` (+140), new
  `tests/test_schedule_consumer.py` (+466), and this notes tree. No
  scripts/, CI workflow, or gate config changes.
- No premature closure keywords (`fixes/closes/resolves #N`) in any commit
  message on `78bb7290..ec39cd6f`.
- Hosted CI on the exact head: UNVERIFIED — PR #1260 (draft) head is the
  prior aud7 head `d011d646` with checks still in flight; `ec39cd6f` is a
  local merge not yet pushed. The local CI-equivalent gates above are green
  on the exact head.
