---
inventory-delta:
  packages/maistro-core/tests: +3
  tests/: +2
---
# issue-1194-replay-contract-repair

Repair round for the verifier findings against `9379e2490` (issue #1194,
Make Graph-node retry/idempotency semantics enforceable): the branch widened
`InvocationStore.list_effect` to `node_run_id: str | None` (the logical-effect
identity) and updated SQLite/in-memory, but the Postgres twin still filtered
`node_run_id = $2` — binding NULL, matching no rows, so completed-Invocation
dedup and the `UnsafeEffectRetry` guard never fired on the production DB.

## What the repair adds

- `PgInvocationStore.list_effect` accepts `node_run_id: str | None`; `None`
  issues a node-filter-free query (mirrors `SqliteInvocationStore`), so the
  logical-effect history is found on Postgres too.
- `_SCHEMA` (and Alembic revision 042, new) drop `node_run_id` from
  `idx_capability_invocation_effect`, ending the index-shape drift between the
  two durable backends; admission uniqueness
  (`uq_capability_invocation_active_effect`) keeps `node_run_id` in both.
- `_wire_capability_invocations` binds concrete stores before calling
  `ensure_schema` (a wiring concern the `InvocationStore` protocol does not
  carry), clearing both documented mypy errors at container.py:2459-2460.
- The dead, contract-contradicting `idempotent: ClassVar[bool]` on the
  unregistered builders `_StageNode` is removed; replay policy lives only in
  the `ReplaySemantics` contract.

## Net suite delta (+3 core, +2 root)

Core (`packages/maistro-core/tests/capabilities/test_pg_invocation_store.py`):
the fake asyncpg pool now emulates both `list_effect` SQL shapes faithfully
(a present `node_run_id=$2` filter binds its argument exactly — NULL matches
nothing; an absent filter spans NodeRuns) with the real ordering. Three cases:
the logical lookup spans NodeRuns and stays run/binding/effect-scoped;
`InvocationExecutionService.invoke(logical_effect=True)` replays one completed
Invocation across a new NodeRun/Attempt without a second dispatch or INSERT;
a live RUNNING Invocation from another NodeRun raises `UnsafeEffectRetry`.
The old store returns `[]` for the logical lookup under this fake — these
pins fail against `9379e2490` and pass here.

Root (`tests/migrations/`): new `test_capability_invocation_effect_index_migration.py`
pins 042's chain wiring (single head) and the exact index drop/create shapes
for upgrade and downgrade. `test_audit_scope_migration.py` and the
capability-table migration scan pin are updated to enumerate 042 (same
strictness — any further migration touching `capability_invocations` still
fails); their node counts are unchanged.

## CI-gate repair round against `1e02cf2` (no suite delta)

The verifier run at `1e02cf2` failed five CI jobs. Repairs, all evidence
driven, none cosmetic:

- SAST: `SqliteInvocationStore.list_effect` composed its SQL with an f-string
  fragment (bandit B608 at invocation_store.py:184). The method now issues two
  fully literal statements — one per `node_run_id` arity — mirroring the
  PostgreSQL twin; behaviour and parameters are unchanged.
- Quality gate: the `claim_run_by_effect` implementations (memory/SQLite/PG)
  and `InvocationExecutionService.invoke` had crossed the radon C threshold
  against the trusted baseline. The optional parent-chain validation moved into
  a `_require_locked_parent_scope` helper per store and the admission-race
  re-read moved into `_completed_replay_after_admission_race`; pure code motion,
  all suites (including the PostgreSQL legs) pass, and the ratchet reports
  70 → 70 reviewed blocks with no new findings or regressions.
- exact-debt-ledger / shipped-surface: the new A2A admission route
  (`POST /tasks/create:create_a2a_task`) is now classified in
  `quality/shipped-surface-truth.json` as canonical (it admits one idempotent
  remote delegation through `RunStore.claim_run_by_effect`).
- exact-debt-ledger / vulture: the two new FastAPI handlers are banked in the
  `fastapi-route-handler` findings ledger (candidate bookkeeping); the grant
  that authorizes them against the trusted base must land on the integration
  base in a separate change by design (`ratchet_provenance.load_authorizations`
  reads grants from the base revision, so a branch cannot authorize its own
  debt). Two store methods this branch added with no caller anywhere —
  `update_run_provenance` (×3 stores, dead) and `find_child_run_by_effect`
  (×3 stores, one test caller) — are deleted per the ledger's own policy that
  new unreachable-code findings must be fixed, never allowlisted; the delegate
  replay test now asserts the child Run through `find_run_by_effect` and adds
  the parent-scope binding assertions, so the replay proof is unchanged in
  strength.
