---
inventory-delta:
  packages/hive-conductor/backend/tests: +13
  packages/maistro-evolve/tests: +7
---
# 1064-evolve-replay-publication

#1064 makes Evolve's battle/finalize publication replay-safe and
reconstructible after a genuine process restart, and the tests come with it.

`packages/maistro-evolve/tests +7` — `test_domain_reconstruction.py` pins the
serialization contract both halves of recovery depend on: a tournament
export restores to a semantically identical instance (ratings, full battle
history with each battle's canonical publication identity, next id,
publication index), genome snapshots round-trip byte-identically, unknown
snapshot versions fail loudly instead of half-restoring, and the crash-vs-
resume comparison signature survives the exact json round-trip a durable
snapshot takes.

`packages/hive-conductor/backend/tests +13` — `test_evolve_domain_store.py`
(10) covers the three honest store backends agreeing on the contract
recovery relies on: snapshots by kind latest-first, the battle publication
primary key as an exactly-once fence (two racing publishers cannot both
insert — proven on real PostgreSQL via two independent pools and a
subprocess when `MAISTRO_TEST_PG_DSN` is set), finalize markers as latest-
payload upserts, and ordered journal replay past a sequence watermark.
`test_evolution_restart_replay.py` (3) is the fault-injection proof at the
domain-mutation → Attempt-commit boundary: a killed process that durably
committed a battle row but never applied it in memory resumes on a fresh
process (its own sqlite spine, store, domain objects) with exactly one
battle, one outcome, one Elo update; a committed finalize is idempotent
evidence across restart; a faulted finalize fails closed with the
compensating admission snapshot restored, never a silent retry. Pair plans
are seeded from the logical cycle identity, so the uninterrupted reference
and the kill+resume execution are byte/semantically comparable.

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->
