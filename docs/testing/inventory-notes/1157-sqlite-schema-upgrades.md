---
inventory-delta:
  packages/maistro-core/tests: +7
---

Adds one parametrized multiprocessing regression test covering concurrent upgrades of the four legacy SQLite schema shapes represented by the five affected store families named by issue #1157, one rollback-and-retry test, one configured-wiring failure test, and one legacy capability-invocation column upgrade test. The process workers use separate SQLite connections so the database-level `BEGIN IMMEDIATE` discipline is exercised rather than only an in-process asyncio lock; the retry test proves a failed DDL step does not leave a partial schema, the wiring test proves an incompatible configured database error is not replaced by an in-memory store, and the invocation test covers the shared discipline's non-memory schema branch.
