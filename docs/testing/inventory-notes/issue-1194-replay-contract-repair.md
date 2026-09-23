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
