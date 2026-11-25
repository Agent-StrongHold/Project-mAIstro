---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# 1064-evolve-replay-pg-legs

Adds `test_evolution_restart_replay_pg.py` (2 tests) to close the two
evidence-backed acceptance gaps the #1064 verifier recorded against the
sqlite-only proof:

1. `test_pg_process_death_between_journal_and_attempt_resumes_exactly_once` —
   the restart-replay headline re-proven at Run level over the production
   spine: a migrated PostgreSQL database through `PgProjectScopeStore` /
   `PgRunStore` / `PgGraphContinuationStore` plus the `PgEvolveDomainStore`
   publication ledger. The interrupted process's asyncpg pool is closed
   entirely before the restarted process opens its own, so the recovery
   mechanism is literally fresh PostgreSQL connections; every leg is a
   distinct connection authority. The restarted process restores the domain
   from the ledger (replaying the battle row the dying process committed but
   never applied in memory), resumes the exact Run through
   `resume_due_graph_runs` with Evolve's own `_recovery_resolver`, and the
   uninterrupted reference (its own fresh pool, same workspace so the pair
   plan seed matches) must equal the recovered outcome exactly: battle
   outcomes, every Elo rating, recovered population ids and fitness, and a
   journal holding exactly one row per logical battle. Reference domain rows
   are purged before the crash leg is admitted so the restart's journal is
   exactly the crash run's own history.
2. `test_pg_committed_finalize_is_idempotent_across_restart` — a committed
   finalize marker survives the fresh-connection restart as evidence: the
   byte-identical post-cycle population is restored from the committed
   snapshot, the same logical finalize replays to the same committed output,
   and nothing re-mutates (no second cull, child, or cycle advance).

Skipped unless `MAISTRO_TEST_PG_DSN` names a reachable, migrated server, like
every other PG-leg suite in this repo. The sqlite twin
(`test_evolution_restart_replay.py`) is unchanged; this module imports its
choreography helpers (seed population, kill seam, restore, domain signature)
instead of copying them, so the two backends cannot drift apart.

Also in this change (no count impact): the cross-product parity suite's
Evolve scenario (`tests/cross_product_parity/test_cross_product_parity.py`)
replaced its abstaining scaffold with the real executed Evolve -> Conductor
scenario (#459 scenario 3, #1069 item 2), carrying #1064's durable
publication ledger in its observation; the `tests/` suite's node-ID count is
unchanged because only test bodies were replaced.
