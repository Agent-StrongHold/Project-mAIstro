---
inventory-delta:
  packages/hive-conductor/backend/tests: +11
---
# 1064: finalize boundary fault injection and distinct-process PG recovery leg

Eleven new collected legs in `test_evolution_restart_replay.py` /
`test_evolution_restart_replay_pg.py`, all acceptance-driven (#1064):

- **+8** — `test_hard_kill_after_each_finalize_boundary_recovers_exactly_once`
  parametrized over the four finalize mutation boundaries the issue names
  (cull, breed, self-improve, migrate) × restart spine backend
  (sqlite, postgres). The replay doubles no longer configure the boundaries
  away (`cull_pct` 0.0→0.25, `island_count` 1→2, `migration_interval`
  1000→1, real self-improve mutation): every kill lands AFTER the named
  mutation applied, and the restarted process must re-apply the sequence
  exactly once over the compensated admission base, byte-identically with
  the uninterrupted reference.
- **+2** — `test_death_between_committed_snapshot_and_marker_refuses_honestly`
  × backend: the `_publish_finalize_committed` sub-window where the committed
  snapshot is durable but the completion marker is not. Pins the honest
  landing (explicit terminal failed/recovery-blocked disposition, committed
  domain intact, no re-application, no false COMPLETED) and documents that
  finalize completion keys off markers alone.
- **+1** — `test_pg_distinct_os_process_recovers_killed_run`: the issue's
  distinct-process launch requirement. The recovery half runs in a fresh
  child interpreter (own asyncpg pool, deterministic double bound in-child),
  which must land the killed Run on exactly the parent's reference outcome.

No production behavior changed except one docstring: `recover_stranded_
evolution_runs` now describes the actual split disposition (RUNNING-stranded
→ terminal FAILED; unmatched QUEUED candidates stay QUEUED per the shared
legacy-DAG candidate-local contract) instead of claiming blanket FAILED
terminalization. 4529 → 4540.
