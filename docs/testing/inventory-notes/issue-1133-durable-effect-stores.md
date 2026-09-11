---
inventory-delta:
  packages/maistro-core/tests: +27
---
# Issue 1133 Durable Effect Stores

Net **+27** for `packages/maistro-core/tests`, from five compensating movements:

- **+2** — two new integration tests in `test_container_capability_effects.py`
  covering the shipped Container effect path: SQLite selects durable
  Binding/Invocation stores and one canonical backend-selected EventStore, with
  Binding and Event persistence visible after Container restart; and two
  independent SQLite connections racing the same logical capability Invocation
  identity leave exactly one authoritative row.
- **-1** — `capabilities/test_invocation_layer_states_its_reach.py` dropped one
  net test while being rewritten for the durable composition: three obsolete
  "nothing wires/migrates this yet" assertions were replaced by two pinning the
  new `capability_invocations` migration and the backend-selected Binding store
  types.
- **+21** — `capabilities/test_capability_store_conformance.py`: the behavioral
  conformance suite for the capability-effect family now runs over all three
  backends (memory, SQLite, PostgreSQL), matching what the durable-event family
  got in #135. Seven behaviors — Binding round-trip/scope resolution,
  Binding immutability, Invocation provenance round-trip, `list_effect` scoping,
  failed-effect reopen, reopen refusal, and database-enforced logical effect
  identity — × 3 parametrized backends. The identity-enforcement case skips on
  `memory://` at run time by design (its stores have no cross-process meaning),
  but all 21 node IDs collect; the PostgreSQL leg honestly skips without
  `MAISTRO_TEST_PG_DSN` and fails the job under `MAISTRO_REQUIRE_PG_LEGS`.
- **+3** — regression coverage for one cached pre-Container default effect context
  and blank approval actors rejected by both in-memory and SQLite stores.
- **+2** — SQLite replica races prove only one provider dispatch occurs for a logical
  Invocation and duplicate logical approvals reconcile to one persisted request.
