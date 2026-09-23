---
inventory-delta:
  packages/maistro-core/tests: +0
---
# auto-1195 develop reconciliation

Resolves the in-flight merge of `ba2f1f07` (develop) into the #1195 governed
PM-polling branch. Both branches evolved the same capability files, so the
conflicts were resolved semantically rather than textually:

- `compose_node`/authorities (develop #1193) supersedes the branch's
  `_di_node` if-chain in `container.py`; the three PM nodes now declare
  `optional_authorities = {"effect_context": "effect_context"}` so the
  container's durable Binding/Invocation authority still reaches them. Without
  the declaration the resolver built them bare onto the process-default
  context, silently reverting the issue's container wiring.
- `PgInvocationStore` is canonicalized to develop's
  `maistro.capabilities.pg_invocation_store` (revision CAS + partial unique
  index); the branch's weaker in-module copy was removed, and
  `SqliteInvocationStore.claim` was strengthened to `BEGIN IMMEDIATE` +
  IntegrityError conversion so cross-connection claims cannot double-dispatch
  (pinned by develop's two-connection race test).
- Invocation admission keeps both designs: claim-preferring stores plus
  develop's race re-read on `UnsafeEffectRetry`; the COMPLETED-return and
  duplicate-status guards run in `invoke()` after `_admit_effect`.
- `ResolvedBinding.workspace_id/project_id` keep develop's empty-string
  defaults so pre-scope durable rows still deserialize for reconciliation;
  Binding-scope correlation stays enforced at the `Invocation` validator
  whenever the snapshot carries scope.

Test delta: no net count change. One develop test
(`test_container_wires_capability_store_to_sqlite_connection`) was rewired to
the surviving `_wire_capability_effects` seam, and two doc-pinning tests
collapsed to develop's names with identical assertions.
