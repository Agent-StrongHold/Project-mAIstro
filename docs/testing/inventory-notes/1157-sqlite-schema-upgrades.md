---
inventory-delta:
  packages/maistro-core/tests: +5
---

Adds one parametrized multiprocessing regression test covering concurrent upgrades of the four legacy SQLite schema shapes represented by the five affected store families named by issue #1157, plus one rollback-and-retry test. The process workers use separate SQLite connections so the database-level `BEGIN IMMEDIATE` discipline is exercised rather than only an in-process asyncio lock; the retry test proves a failed DDL step does not leave a partial schema.
