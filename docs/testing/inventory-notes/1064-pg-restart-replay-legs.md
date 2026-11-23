---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---
# #1064: evaluation/finalize restart-replay legs over SQLite and PostgreSQL

Adds 6 collected cases in `test_evolution_restart_replay.py`: the three
restart-recovery scenarios (evaluation receipts, committed-finalize
evidence, hard-kill mid-finalize) each parametrized over SQLite and
PostgreSQL via a shared `restart_spine_factory` fixture. The PostgreSQL
legs run against the production `PgEvolveDomainStore`/`PgRunStore`/
`PgProjectScopeStore` spine with a brand-new asyncpg pool per process leg —
nothing survives a restart but the server's durable rows — and skip only
when `MAISTRO_TEST_PG_DSN` is absent. Because the PG legs share one server,
the reference leg's durable rows are purged before the crash leg is
admitted, so the restarted process's journal is exactly the crash run's own
history.

The scenarios pin the three crash windows the issue names at the
domain-mutation → Attempt-commit boundary:

1. Death between an evaluation publication and its Attempt terminal: the
   restore must replay the committed evaluation receipts, so recovery
   resumes with scored genomes (never the unscored admission snapshot) and
   still fights exactly the remaining battles.
2. Death after the committed finalize marker and snapshot but before the
   finalize Attempt terminalizes: recovery must land on the committed
   evidence, accept the legitimately diverged (culled/bred) membership,
   and complete the Run idempotently.
3. A `BaseException` mid-finalize (no fault handler runs, marker stays
   `in_progress`): recovery restores the compensated pre-finalize base and
   transparently re-runs the sequence once, while a caller holding
   partially-mutated live memory still refuses.

Each leg compares against an uninterrupted reference run on the same
backend: same members, same fitness, same battle outcomes and Elo ratings
(`_domain_signature`), byte-identical genome exports where the contract
asks for byte equality.

No canonical spine changes: `Goal -> Graph -> Run -> NodeRun -> Attempt`
remains the only execution authority; the Evolve domain ledger only makes
an already-published effect reconstructible, never a second scheduler.

## Executed validation

- Against the pre-fix production code (`c48b176b9276`) all 6 new cases
  failed, reproducing the reported defects (unscored resume, committed
  finalize stranded behind an unterminal Attempt, transparent resume
  refused); against the repaired tree all 6 pass with
  `MAISTRO_TEST_PG_DSN` pointed at a migrated PostgreSQL 18 server, and
  the SQLite legs pass without one.
