---
inventory-delta:
  packages/hive-conductor/backend/tests: +14
  packages/maistro-evolve/tests: +9
---
# pr-1064-1065-evolve-replay-safety

Closes #1064 (battle/finalize replay-safety + a restart/recovery resolver for
Evolve's canonical Graph adapter). #1065 (pair-plan/graph capacity fencing)
was already fixed on `develop` by #1299/#1300 before this branch was cut;
this PR adds only its PR #947 review-thread disposition, no new #1065 code
or tests.

`packages/maistro-evolve/tests` (+9): `test_tournament.py::TestBattleIdempotency`
(5 tests) proves `EloTournament.record_battle()`'s new `node_run_id`/
`attempt_id` idempotency key — no-identity callers always record fresh, a
replayed `(node_run_id, benchmark)` is a no-op returning the original
`GenomeBattle`, a NodeRun spanning several benchmarks that faults partway
through only replays the unpublished ones, and a genuinely new `node_run_id`
is never suppressed. `test_population.py::TestCycleMarkers` (4 tests) proves
`PopulationStore`'s new `record_cycle_marker`/`get_cycle_marker` idempotency
ledger (used by Evolve's finalize node to avoid double cull/breed/
self-improve/migrate on a recovered Attempt).

`packages/hive-conductor/backend/tests` (+14): `test_evolution_canonical_graph.py`
(+3) proves battle and finalize idempotent replay through the real
`_TournamentWork`/`_finalize_cycle` wiring (Elo/battle-count unchanged across
a same-`node_run_id` replay; finalize's mutation count stays at 1; a fault
partway through finalize blocks automatic retry with
`FinalizeReconciliationRequired` instead of double-mutating or silently
succeeding). `test_evolution_recovery.py` (new, 8 tests) proves the new
`_recovery_resolver`/`recover_stranded_evolution_runs`/
`wake_due_evolution_runs` — the restart path PR #947 flagged as missing:
resolver-level blocked cases (service not started, no domain state,
population mismatch), a resolver-level success case, and two end-to-end
cases through the real canonical recovery seam (a stranded QUEUED Run
recovers to COMPLETED when this process's population matches; one that
doesn't match is isolated and left QUEUED for a later tick rather than
resumed against the wrong population), plus a wiring proof and an
unavailable-engine no-op proof. `test_evolution_recovery_cadence.py` (new,
3 tests) proves the periodic driver starts/stops, survives one failing tick,
and is idempotent to start twice — mirroring `test_dag_recovery.py`'s
existing cadence tests for the legacy DAG adapter's driver.
