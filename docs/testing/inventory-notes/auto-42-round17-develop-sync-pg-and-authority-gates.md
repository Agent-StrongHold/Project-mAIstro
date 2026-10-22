---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-canvas/tests: +0
---

# auto-42 round 17: develop sync (8c8fc8d67), PG-verified persistence, authority-gate correction

Repair round at merge of `origin/develop` `8c8fc8d67` into `auto-42`. Three
inputs: (1) the previous block was an in-progress develop sync merge left with
two unresolved conflict files; (2) the round-16 verify BLOCKED on "claimed
`check_direct_effects.py` does not exist" and on PostgreSQL persistence being
UNVERIFIED (Docker daemon down); (3) develop's P0.8 store-boundary burn
(`053f93969`, #364) tightened `RunStore.create_run` / `claim_run_by_effect` to
require a non-empty `actor_principal_id`, which the lane's own effect-claim
tests predate.

## Develop sync completed

- `219d28281` — completes the preserved merge of `053f93969` (P0.8 store
  boundary). Conflict resolutions, both test-only:
  - `test_attempt_executor.py`: `test_non_retryable_contract_overrides_a_graph_retry_budget`
    keeps the branch's `_hard_non_retryable_graph`/`_hard_non_retryable_resolver`
    rework (#1194: a NON_RETRYABLE label overrides the graph budget) and adopts
    develop's `actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID` kwarg.
  - `test_agent_delegate_remote_child_run.py`: keeps the branch's deletion of
    `test_replaying_the_same_logical_delegation_reuses_the_child_and_task`,
    `test_independent_worker_reuses_receipt_without_local_task_deduplication`,
    `test_concurrent_workers_atomically_claim_one_child_and_task`, and
    `TestParentageIsVerifiedBeforeAdmission`. Rationale: the replay-adoption
    behaviour moved to the durable effect-claim contract (conformance in
    `test_spine_conformance.py` effect-claim tests + `test_idempotent_replay_conformance.py`),
    and the parentage invariant is durably enforced by the store itself
    (`runs/store.py` "parent_node_run_id does not belong to parent_run_id",
    pinned by `test_spine_conformance.py:300` and the sqlite/pg store suites).
    This matches the reconciliation recorded in
    `issue-1194-develop-sync-resolution.md` item 1.
- `b62ef3bfa` — merge of `origin/develop` tip `8c8fc8d67` (M4-C Evolve
  fitness); auto-merged clean.

## actor_principal_id threading (P0.8 gate fallout, test-side only)

All production `create_run` call sites already pass an actor (audited:
`canonical_execution.py:184`, `master.py:631`, `admission.py:1450`,
`runs/admission.py:115`, `runs/service.py:82`, `graph_executor.py:882`,
`pack_fixtures.py:350/733`, `agent_synth_dag.py:372`,
`agent_delegate_remote.py:886` inherits the parent's actor;
`maistro_server/api/a2a.py:89` passes the authenticated principal —
`verify_api_key` never returns None, so the `else None` arm is unreachable).
The lane's tests that predate the gate were updated to pass
`DEFAULT_TEST_ACTOR_PRINCIPAL_ID`:

- `tests/graph/durable_runs/test_ambiguous_effect_replay_guard.py` — the
  pre-admitted Run for the replay-guard run.
- `tests/graph/durable_runs/test_attempt_executor.py` —
  `test_unkeyed_effect_contract_overrides_a_graph_retry_budget`.
- `tests/runs/test_spine_conformance.py` — six `claim_run_by_effect` calls in
  the effect-claim conformance tests, including the two refusal tests: on
  PostgreSQL the actor gate runs during Run construction, *before*
  `validate_effect_claim_parent`, so the pinned RunIntegrityError is only
  reachable with a valid actor supplied (in-memory orders the checks the other
  way; both refuse, and the tests now assert parentage refusal on all legs).
- `tests/runs/test_sqlite_store.py` — the `find_run_by_effect` claim round-trip.

No test was added or removed; suite counts are unchanged (`+0` deltas above).

## PostgreSQL persistence now executed (round-16 finding 2 closed)

Docker is still unavailable (`docker version` cannot connect), but PostgreSQL
18.6 server binaries are installed locally; a throwaway instance
(127.0.0.1:54329, user `maistro`, db `maistro_test`, trust auth) replaced the
CI service container, and CI's exact postgres-job steps were executed against
it:

- `pytest tests/migrations/test_migration_chain.py` — 13 passed.
- `alembic upgrade head` → `alembic downgrade base` → `alembic upgrade head` —
  clean round trip on the merged chain (049/050 tips).
- `pytest packages/maistro-core/tests/persistence` — 705 passed.
- `pytest packages/maistro-core/tests/test_container_postgres.py` — 15 passed.
- `MAISTRO_REQUIRE_PG_LEGS=1 pytest packages/maistro-core/tests/workspaces` —
  328 passed, 2 skipped.
- `MAISTRO_REQUIRE_PG_LEGS=1 pytest
  packages/maistro-server/tests/api/test_canvas_supported_path.py` — 7 passed.
- PG-marked lane stores: `test_pg_invocation_store.py`,
  `test_pg_store_internals.py`, `scheduling/test_pg_admission.py`,
  `test_effect_context_convergence.py`, `security/test_elevation_durable.py` —
  45 passed.
- Full `packages/maistro-core/tests` with PG legs — 12224 passed, 47 skipped,
  1 xfailed (vs 11466/788 without DSN: the PG legs now execute, not skip).
- Lane battery with PG legs — 693 passed, 0 skipped.

## Authority-gate correction (round-16 finding 1 closed)

`scripts/check_direct_effects.py` does not exist and never did; the round-16
note's citation was wrong. The "no direct physical execution bypass" criterion
is evidenced by the gates that do exist, all run this round at the merged head:

- `check-execution-lifecycles.py` — 19 lifecycles, all classified (exit 0).
- `check-owned-store-access.py` — every chat_sessions/memory_entries access
  goes through OwnedStore (exit 0).
- `check-agent-store-writes.py` — stores.agents mutated only by
  agent_materialization.py (exit 0).
- `check-reachability.py` — 1207 production modules scanned (exit 0).
- Plus the Attempt-routing tests: the durable executor routes every NodeRun's
  work through the Attempt runtime (`test_attempt_executor.py::test_public_durable_executor_routes_each_node_run_through_attempt_runtime`),
  and the effect-claim conformance pins one canonical claim path per backend.

## Other gates at the merged head

- `ruff check .` / `ruff format --check .` — clean.
- `check-suite-inventory.py` (CI's argumentless invocation) — 14 suites match.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` — 1361/1361 reviewed identities (exit 0).
- `check-radon-baseline.py` — 145/145 (exit 0).
- Diff-coverage gate with CI's exact producer (`coverage run --branch
  --source=scripts -m pytest tests/`, then `check-diff-coverage.py
  coverage.xml --base origin/develop`) — exit 0; root suite 4295 passed.
- Child issues: #1169, #1170, #1194 all CLOSED (`gh issue view`, read-only).
  #232 (RUNNING-Attempt reconciliation) is a listed child but is not one of
  the three the acceptance clause gates on; still OPEN and tracked.

## Known pre-existing failures not introduced here

- `formal/models/test_rsi_audit_trail_conformance.py` and
  `test_rsi_rollback_conformance.py` fail collection with an ImportError;
  both files are byte-identical to `origin/develop` (inherited, not lane
  scope). `formal/models/test_run_lease_fence.py` — the chat lease/fence model
  this lane modified — passes against the live PostgreSQL instance.
