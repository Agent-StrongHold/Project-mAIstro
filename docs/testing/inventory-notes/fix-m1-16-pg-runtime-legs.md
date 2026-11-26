---
inventory-delta:
  packages/maistro-core/tests: +9
---
# M1 #16: PostgreSQL runtime legs for the event/recovery plane

The first implementation round of the M1 event/recovery plane (#16) closed
with one unverified acceptance surface: the canonical EventStore and the
pool-backed recovery wiring had only memory and SQLite evidence. These nine
node IDs run the same claims against a real PostgreSQL server
(`MAISTRO_TEST_DATABASE_URL`; hard-failing under `MAISTRO_REQUIRE_PG_LEGS`,
skipping without a URL, per the established `_require_postgres` pattern):

- `test_durable_store_conformance.py::TestReplayCursor` — the durable replay
  acknowledgement (#836/#1163) is monotonic and rejects negative positions on
  all three backends, including PostgreSQL (6 node IDs: 2 tests × 3 backends);
- `test_durable_store_conformance.py::test_pg_replay_cursor_survives_a_pool_restart`
  — the PostgreSQL cursor survives a closed and reopened pool, mirroring the
  SQLite restart test;
- `test_backend_effect_context.py::test_backend_context_injects_one_postgres_event_store`
  — `new_backend_effect_context(pg_pool=...)` (#1133) selects `PgEventStore`,
  creates its schema, and round-trips a canonical event through the server
  with a server-assigned Workspace sequence;
- `test_container_pg_durable_events.py::TestPoolSelectsThePostgresStores::test_the_pool_selects_the_canonical_event_publisher_store`
  — a pool-wired container's `canonical_event_publisher` is the
  `CanonicalEventStoreSink` delivery wrapper around the *same object* injected
  into `capability_effects.event_store`, and a recovery-disposition event
  published through it reaches `canonical_event_log` on the server.

No production code changed for these legs beyond a docstring clarification on
`CanonicalEventStoreSink` (the adapter owns no Event semantics of its own).
