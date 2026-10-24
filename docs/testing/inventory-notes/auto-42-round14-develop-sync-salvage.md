---
inventory-delta:
  packages/maistro-core/tests: +7
---
# auto-42 round 14: develop-sync salvage (two-step merge) to origin/develop f5fa43771

Salvage of the in-progress develop-sync merge that round 13 left blocked. The
driver had started the sync against stale develop `3082279f1` (an ancestor of
the current tip); this round completed that merge, then merged the current
`origin/develop` (`f5fa43771`) on top, so the branch carries develop's full
tip, including the #1321 governed-effect seam and the Wave 2 principal
ratchets.

## What the merge reconciliation did

- `capabilities/invocation.py`: kept the lane's canonical `effect_scope` /
  `effect_identity` contract (the `logical_effect` flag was retired earlier in
  this lane, documented in `auto-42-develop-sync-55be1459-reconciliation.md`)
  while adopting develop's structural seam: `EffectClaimStore` protocol,
  `_admit_effect`, module-level `_settled_by_another_admission`, and the
  `on_completed` recorder hook (#718) on every terminal path. The post-admission
  re-read was translated to re-read the caller's stable scope.
- `capabilities/invocation_store.py`: develop's new `SqliteInvocationStore.claim`
  was translated to the `effect_scope` schema (the auto-merge had carried in a
  body still keyed on the retired `logical_effect` column): the pre-insert
  history read and the partial unique index both key the normalized
  `effect_scope or node_run_id` identity.
- `tests/capabilities/test_invocation_store.py`: develop's new claim/race
  coverage (12 tests) was translated to the effect-scope model rather than
  dropped; the lane's own tests were kept. Two of the translated tests were
  corrected to respect the admission invariant that only FAILED priors may
  share an identity with a live claim.
- `tests/capabilities/test_binding_invocation.py`: kept both sides' tests —
  the lane's cross-NodeRun effect-scope dedup test and develop's
  deduplicated-handout ledger-repair test.
- `tests/capabilities/test_pg_invocation_store.py`: kept the lane's
  dedup assertions and added develop's container-wiring test for the PG
  ledger.
- `alembic/versions/036_audit_log_org_scope.py`: took develop's re-parent
  narrative; the verified chain is single-headed at `048` with no cycles or
  dangling refs.
- `tests/migrations/test_capability_invocation_effect_index_migration.py`:
  kept the lane's deletion (documented in
  `auto-42-develop-sync-55be1459-reconciliation.md`): it tests migration 043,
  the `logical_effect`-era index migration this lane retired as a competing
  mechanism. The effect-scope admission contract is covered by
  `035`'s `uq_capability_invocation_active_effect` plus the sqlite/pg service
  tests.
- `container.py`: removed one `# type: ignore[assignment]` that develop's own
  re-typing (`invocation_store: Any`) left unused (mypy `unused-ignore`).
- `docs/testing/inventory-notes/p0-1-principal-migration-wave2a.md` and
  `feat-cutover-p0.2-route-registry.md` (develop's Wave 2 notes): their
  `inventory-delta:` blocks used free-text entries this gate cannot parse
  (`migrated`, `quality/: +3`), which failed `check-suite-inventory.py` for
  every branch carrying develop's tip. Neither wave changed a recorded suite
  count, so the blocks were removed rather than guessed at.
- `ruff format` on three files that fail `ruff format --check .` byte-identical
  at develop's tip (`hive-conductor routes/audit.py`,
  `services/agent_materialization.py`, `durable_runs/canonical_store.py`):
  mechanical line wrapping only, required for the format gate to pass.

## Executed evidence (at this head)

- `uv run pytest packages/maistro-core/tests/graph/durable_runs
  packages/maistro-core/tests/tasks packages/maistro-core/tests/runtime
  packages/maistro-core/tests/runs
  packages/maistro-core/tests/observability/test_execution_correlation.py -q`
  -> **2083 passed, 296 skipped**.
- `uv run pytest packages/maistro-core/tests/capabilities tests/migrations -q`
  -> **459 passed, 81 skipped** (skips are the PG-parametrized cases;
  `MAISTRO_TEST_PG_DSN` is unset in this environment, so the PostgreSQL legs
  remain UNVERIFIED in this round — same residual as round 13).
- `uv run pytest packages/maistro-core/tests/events -q` -> 331 passed, 51
  skipped; `uv run pytest packages/maistro-core/tests/quota -q` -> green.
- `uv run ruff check .` and `uv run ruff format --check .` -> clean.
- `uv run mypy packages/maistro-core/src packages/maistro-server/src
  packages/maistro-turing/src packages/maistro-canvas/src
  packages/maistro-bootstrap/src packages/maistro-registry/src` ->
  **Success: no issues found in 748 source files**.
- `uv run python scripts/check-execution-lifecycles.py`,
  `check-lifecycle-provenance.py`, `check-durable-table-inventory.py`,
  `check-merge-markers.py`, `check_direct_effects.py`, `check-enumerations.py`,
  `check-reachability.py` -> all pass.
- `uv run python scripts/check-suite-inventory.py` -> all suites match after
  recording this note's `+7` for `packages/maistro-core/tests` (the tests this
  merge added/translated that no earlier note recorded; net drift was positive,
  every other suite exact, so no collection regression).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` -> passes once the
  sync-merge commit exists, because the trusted base then resolves to
  `f5fa43771` (merge-base of the branch and develop). Against the stale
  `3082279f1` base the pre-commit state legitimately reports trusted-ledger
  deltas that the develop tip's own Wave 2 banking commits already pruned/banked.

## Residuals (pre-existing at develop's tip, not introduced by this merge)

- `packages/maistro-core/tests/test_container_wiring.py`: 8 passed, 34 errors
  identically on a clean develop checkout at `f5fa43771` (verified in a
  disposable detached worktree): develop's autouse `governed_pm_bindings`
  fixture hits a container effect context that an earlier test in the file
  (`test_sqlite_backend_wires_sqlite_durable_event_stores`) bound and never
  unbound, whose SQLite connection belongs to the previous event loop.
  Every file in the failure path is byte-identical to develop's.
