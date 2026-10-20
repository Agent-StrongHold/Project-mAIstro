---
# Trunk exact-debt vulture sweep inventory note

inventory-delta:
  packages/maistro-core/tests: -6
  tests/: -8
---

## Claim

**−6 `packages/maistro-core/tests` against the recorded ledger** — the sweep
itself deleted 16 node IDs and relocated 1 (net −15); the remaining +9 is
trunk ledger drift that develop never banked (develop `cdf7343d` collects
10306 vs recorded 10297 — verified by running this gate on a develop
worktree: identical DRIFT). Recorded as −6 so the composition zeroes; the
+9 is trunk's to bank properly. The `tests/` −8 is likewise trunk ledger drift, not a branch property:
collected 3442 identically on develop `cdf7343d` and this branch, locally
AND on CI (the CI C1 gate reports the same DRIFT) — a recent trunk change
removed 8 node IDs from `tests/` without banking. Banked here so the
composition zeroes; trunk should reconcile the ledger bank properly.

Removes four Vulture findings that exist on `develop` but are invisible to
develop's own exact-debt-ledger gate (the trusted-base scan is
self-reference-blind on trunk), which fail every candidate PR that merges
develop. This is the checker's documented lane-legal path: delete the debt
instead of editing the ledger.

Symbols removed (each verified to have zero production readers — only write
sites and test asserts on dead counters):

- `PurgeOutcome.event_references_retained` (field, `maistro/runs/store.py`)
- `PurgeOutcome.schedule_claims_released` (field, `maistro/runs/store.py`)
- `_LegacyGraphPipelineExecutor` (class, `maistro/builders/graph_executor.py`,
  with its private `_Outcome`/`_GateRoute` enums)
- `RunRetentionSweeper.last_outcome` (property, `maistro/runs/retention.py`,
  with the write-only `_last_outcome` bookkeeping)

Orphans removed with them: sqlite `_RETAINED_REFERENCE_SQL`, the pg
`schedule_id` projection in both purge-candidate SELECTs, the pg
`events_retained` count block, and the in-memory/`sqlite` count wiring.

## Test changes (all in `packages/maistro-core/tests`)

- Deleted `tests/builders/test_graph_executor.py` — 14 async tests exercised
  only `_LegacyGraphPipelineExecutor`. Its surviving-content test
  (`_build_prompt` malformed-format fallback) was relocated unchanged into
  `tests/builders/test_canonical_execution.py`.
- `tests/builders/test_canonical_execution.py`: dropped the legacy-oracle half
  of four parity tests and renamed them (`test_stage_wave_creates_...`,
  `test_skip_and_unsupported_stage_domain_projection`,
  `test_failure_and_timeout_terminal_behavior`,
  `test_timeout_never_runs_the_on_complete_hook`,
  `test_canonical_adapter_is_public_and_executor_names_are_not_exported`);
  all canonical-evidence assertions (node runs, attempts, provenance,
  frontier, concurrency) are preserved.
- `tests/runs/test_retention_policy.py`: deleted
  `test_the_outcome_names_the_authorized_workspace` (existed solely to read
  the removed property); trimmed `last_outcome` assertions from five tests
  whose gauge/scope/metric coverage is retained.
- `tests/runs/test_retention_scope_conformance.py`: trimmed the removed
  counter assertions from `test_events_survive_a_purge` (renamed from
  `..._and_are_counted`) and the schedule-claim re-admission test; the
  survival and re-admission behaviors remain asserted.

## Evidence

`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` reports none of the four
identities after this change; scoped pytest suites for every touched module
pass; ruff clean.
