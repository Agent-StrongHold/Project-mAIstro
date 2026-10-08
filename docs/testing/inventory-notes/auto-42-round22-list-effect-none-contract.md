---
inventory-delta:
  packages/maistro-core/tests: +2
---
# auto-42 round 22 — restore the `list_effect(node_run_id=None)` cross-node audit contract

CI-repair round at head 0a3baf9fa (both CI failures, `test` and
`Coverage gate (publish-set floor + diff coverage)`, share one root cause).

## What failed and why

CI at 0a3baf9fa failed exactly one test,
`packages/hive-conductor/backend/tests/test_e2e_authenticated_real_model_graph.py::test_canonical_llm_node_crosses_the_governed_invocation_seam`
(`AssertionError: []` / `assert 0 == 1`), in two jobs: the `test` job and the
coverage gate job, whose combine step re-runs the same suite under coverage
(`1 failed, 3315 passed` → step exit 1). The branch's M1-B2 rework of the
Invocation ledger rewrote `InvocationStore.list_effect` from develop's
`node_run_id: str | None` to `node_run_id: str` and dropped the
``node_run_id is None`` branch, so the cross-node audit read — "every
Invocation under the run for this binding+effect_key" — returned `[]` in all
three store implementations (in-memory, SQLite, PostgreSQL): the SQL branches
bound `node_run_id = NULL`, which matches no row, and the in-memory identity
tuple contained `None`, which matches no `effect_identity`. The unchanged
hive-conductor e2e test (from 3d9afc801) still calls
`list_effect(run_id=..., node_run_id=None, ...)` to assert Invocation evidence
beneath an Attempt.

## The repair

- `packages/maistro-core/src/maistro/capabilities/invocation.py` — protocol
  parameter restored to `node_run_id: str | None` (with the contract
  documented on the protocol method); `InMemoryInvocationStore.list_effect`
  spans every node run of the run when both `effect_scope` and `node_run_id`
  are absent.
- `packages/maistro-core/src/maistro/capabilities/invocation_store.py` and
  `packages/maistro-core/src/maistro/capabilities/pg_invocation_store.py` —
  three-branch `list_effect`: `effect_scope` (logical identity, the #1194
  feature this branch added) takes precedence; a concrete `node_run_id`
  filters on it; `None` drops the discriminator from the query instead of
  binding NULL.
- New regression test
  `test_list_effect_without_a_node_run_spans_every_node_run` in
  `packages/maistro-core/tests/capabilities/test_invocation_store.py` pins
  the None-spanning contract for the SQLite and in-memory stores, including
  run isolation and cross-effect-key exclusion. Verified it fails against the
  pre-fix implementations and passes with the fix. The pg twin gets
  `test_pg_invocation_store_list_effect_without_a_node_run_spans_node_runs`
  in `test_pg_invocation_store.py` (the fake pool dispatches on the issued
  query's SQL shape, so the branchless None query is exercised for real),
  and `_FakePgInvocationPool.fetch` learned the three-parameter shape.

The branch's `effect_scope` behavior is unchanged: the pre-existing
`test_sqlite_list_effect_with_stable_scope_spans_node_runs` still passes, as
does the rest of the capabilities suite (949 passed / 123 skipped across
capabilities + a2a + spine conformance + canvas publishing + the four
affected hive-conductor suite files).

## Re-validation battery at this round's final head

- `uv run pytest packages/hive-conductor/backend/tests --timeout=30 -q`
  (the CI `test` job's failing leg, full suite) — **3322 passed, 6 skipped**;
  the previously failing seam test passes and the same 3328-test collection
  CI saw is green.
- hive-conductor governed-model consumers / canvas egress / legacy DAG node +
  core capabilities + a2a + spine conformance + canvas publishing —
  949 passed, 123 skipped.
- `ruff check .` and `ruff format --check .` — clean; `mypy --strict` on all
  six src trees (CI's exact arguments) — clean (786 files).
- `scripts/check-suite-inventory.py --suite packages/maistro-core/tests` —
  ok at 12603 collected (+2 recorded by this note).
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — exit 0, 1342 reviewed identities, unclassified 0:
  no ledger amendment needed for this round.
- Dependency states (read-only): #1169 CLOSED, #1170 CLOSED, #1194 CLOSED —
  the #42 acceptance dependency list is satisfied as of this round.
