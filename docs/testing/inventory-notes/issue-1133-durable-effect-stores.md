---
inventory-delta:
  packages/maistro-core/tests: +27
---
# Issue 1133 Durable Effect Stores

Net **+27** for `packages/maistro-core/tests`, from five compensating movements:

- **+2** — integration tests in `test_container_capability_effects.py` covering the shipped Container effect path: SQLite selects durable Binding/Invocation stores and one canonical backend-selected EventStore, with Binding and Event persistence visible after Container restart; and two independent SQLite connections racing the same logical capability Invocation identity leave exactly one authoritative row.
- **-1** — `capabilities/test_invocation_layer_states_its_reach.py` dropped one net test while being rewritten for the durable composition: obsolete "nothing wires/migrates this yet" assertions were replaced by checks pinning the `capability_invocations` migration and backend-selected Binding store types.
- **+21** — `capabilities/test_capability_store_conformance.py`: behavioral conformance over memory, SQLite, and PostgreSQL for Binding round-trip/scope resolution, Binding immutability, Invocation provenance, effect scoping, failed-effect reopen, reopen refusal, and database-enforced logical effect identity. The PostgreSQL leg skips without `MAISTRO_TEST_PG_DSN` and fails under `MAISTRO_REQUIRE_PG_LEGS`.
- **+3** — regression coverage for one cached pre-Container default effect context and blank approval actors rejected by in-memory and SQLite stores.
- **+2** — SQLite replica races prove only one provider dispatch occurs for a logical Invocation and duplicate logical approvals reconcile to one persisted request.
