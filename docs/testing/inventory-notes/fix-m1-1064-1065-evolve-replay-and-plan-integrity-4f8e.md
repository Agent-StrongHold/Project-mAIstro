---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
  packages/maistro-evolve/tests: +2
---
# fix-m1-1064-1065-evolve-replay-and-plan-integrity-4f8e

Fixes for the 8 Codex review findings posted against PR #1534's HEAD
(`7fc433d0`, #1064/#1065 restart-recovery for canonical Evolve Runs), plus one
regression test per confirmed-real behavior change. No test was removed or
renamed; every added test targets one finding.

`packages/maistro-evolve/tests/test_tournament.py` (+2): `EloTournament` now
keeps a `_published_battles` index alongside `_battles` so
`find_published_battle` is O(1) instead of an O(n) scan run on every canonical
`record_battle` call, and `get_battle_history()` now includes `node_run_id`/
`attempt_id` in its returned dicts. `test_find_published_battle_is_indexed_not_a_linear_scan`
proves the index (not a scan) answers the lookup by clearing `_battles` after
recording and showing the answer is unchanged. `test_battle_history_exposes_publication_identity`
proves both new fields reach `get_battle_history()`'s output, which is what
the Hive `/tournament/battles` route actually serializes.

`packages/hive-conductor/backend/tests/test_evolution_recovery.py` (+4):
`recover_stranded_evolution_runs`/`wake_due_evolution_runs` now (a) hold
`_EvolutionService.cycle_lock` for their whole execution, the same lock
`seed_population`/a live cycle hold, so recovery can never interleave
evaluate/battle/finalize node execution with a concurrent cycle or seed
request; (b) reject a live population that gained genomes after this Run's
plan was frozen, not just one missing genomes, so a later seed can't have its
genomes silently culled/bred/migrated by a recovered finalize that was never
admitted against them; and (c) hold a persisted `ScanContinuation` per
(seam, store) across ticks, mirroring the legacy-DAG wrapper, so a
bounded-`limit` tick that can't recover the earliest candidates advances past
them instead of reselecting them forever.
`test_recovery_cannot_interleave_with_a_live_cycle_holding_the_lock` has a
fake "live cycle" hold `cycle_lock` and block; asserts a concurrent recovery
call is provably stuck (not done, no domain mutation) until the live holder
releases, then completes correctly afterward.
`test_recovery_is_blocked_when_live_population_gained_genomes_after_admission`
and `test_recovery_seam_is_a_noop_when_population_gained_genomes_after_admission`
seed an extra genome into the population after a stranded Run's plan was
frozen and prove `_recovery_resolver` raises `EvolveRecoveryBlocked` for it
(unit level) and the seam isolates the Run as QUEUED without touching the
seeded genome (end-to-end level).
`test_a_second_recovery_tick_advances_past_previously_unrecoverable_candidates`
admits two Runs this process's live population cannot honestly resume ahead
of a third Run it can, bounds each tick to `limit=1`, and shows the first two
ticks each isolate one unrecoverable candidate (never reselecting the same
one) so the third tick reaches and completes the genuinely recoverable Run.

`packages/hive-conductor/backend/tests/test_evolution_service.py` (+3): the
restart-recovery cadence (`services.evolution_recovery`) now starts inside
`start_evolution()` and stops inside `stop_evolution()` — bracketing the
`_EvolutionService` singleton's own lifecycle — instead of inside
`EngineService.start()`/`stop()`, which previously started the cadence before
the singleton existed (a due RUNNING Run inspected in that window
terminalized FAILED solely from `EvolutionServiceNotStarted`) and stopped it
after the singleton was already cleared at shutdown.
`test_start_evolution_starts_the_recovery_cadence` and
`test_stop_evolution_stops_the_recovery_cadence_before_clearing_the_singleton`
prove the cadence task now exists only while `_service` does, and that
`stop_evolution` stops/joins the cadence before (not after) clearing the
singleton — recorded by tracking that the stop callback ran while `_service`
was still set, not merely that both eventually happened.
`test_starting_the_engine_alone_does_not_start_the_evolve_recovery_cadence`
proves `EngineService.start()` alone (the call application startup makes
*before* `start_evolution()` runs) no longer starts the Evolve cadence at
all — closing exactly the ordering gap the finding named.
