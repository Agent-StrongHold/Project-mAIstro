---
inventory-delta:
  packages/hive-conductor/backend/tests: +51
---

# Startup reconciliation converges the schedule projection on canonical truth (#2467)

`packages/hive-conductor/backend/tests/test_schedule_projection_authority.py`
is new: 51 node IDs — 17 scenarios over the in-memory store, a SQLite store on
a tmp file, and the production ``PgScheduleStore`` on the shared test server
(skips without ``MAISTRO_TEST_PG_DSN``, refuses under
``MAISTRO_REQUIRE_PG_LEGS``, the repo's durable-leg convention) — behind a real
`create_container` Container swapped into the engine. The SQLite and PostgreSQL
leg re-opens the store across the simulated restart, so the canonical rows
under test are the persisted ones.

The routes write the canonical `ScheduleStore` definition first and the Hive
row second, with no shared commit; startup reconciliation used to answer every
crash window by re-putting a Hive-row-derived definition whenever canonical was
missing or drifted — the projection overruling the authority. The new tests
hold the replacement policy: a restart that finds the projection behind an
acknowledged disable, rename, or recurrence edit repairs the projection and
never the definition (cursor-preserving, with the substrate's own
recurrence-clears-due-cursor contract); a deleted schedule stays deleted under
its durable tombstone, and a tombstone-less stale row is degraded and never
reimported; an interrupted create resolves to one visible identity through its
durable pending marker, or closes as never-committed; legacy import happens
exactly once, bounded by the migration marker; recorded cursors, Run ids, and
due state survive repeated and concurrent (two-replica) reconciliation
unchanged; a post-marker startup never runs the import pass for a
canonicalized id; and the fire path reads the definition it spends from
canonical truth, so a stale projection cannot hand an exhausted schedule fresh
quota. The create route's compensation failure path is itself tested: a create
whose Hive write and canonical compensation both fail leaves its marker
standing, and the restart projects the committed row (one identity, no
invisible orphan); a failing marker clear or tombstone write never fails the
already-committed route. `scheduler_status` reports the reconciliation outcome
and degraded rows (#290).

CI-repair round at the ledger/reconciliation gate repair (memory + SQLite legs
re-run locally; +6 nodes): two scenarios pin the import pass's failure policy.
A legacy row with no actor principal (#1201) cannot authorize an import — its
put would refuse — but collecting it as a failure would keep the migration
marker unwritten forever on Hive stores seeded with such a row, bricking the
reconciliation; the scenario proves it is skipped, never imported, named on
the health surface, and that the marker completes and later startups keep
naming it. A transient canonical-store outage during the import raises
`LegacyImportIncomplete`, leaves the marker unwritten, names the failed row,
and a healed store completes the import on the retried pass. The same round
moved the ledger's `schedule_migration` JsonStore out of `stores.py` beside
its only writer (`services.schedule_projection`, the #334/#1048 service-owned
store pattern with `register_json_store` keeping the persistence wiring), so
the cutover retirement ratchet sees no new `stores.py` store and no new
consumer of the retiring `stores.schedules` surface: the projection module
reaches the row map only through helpers in `services.scheduler`, which is
already the tolerated importer. It also fixed the compensation-fails scenario
to drop its projected row, since a strict pass treats a leaked row it cannot
account for as a failure. Two existing tests were updated, not removed: the
runner-startup orchestration patch targets `reconcile_schedule_projection`, and
the `_definition_for` contract test asserts the new read-first authority
(stored definition stands; first put still belongs to a never-canonicalized
row).
