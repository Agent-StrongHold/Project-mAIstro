---
inventory-delta:
  packages/hive-conductor/backend/tests: +14
---
# 1243-schedule-consumer-tick

Fourteen new tests across `packages/hive-conductor/backend/tests` (13 in
`test_schedule_consumer.py` + 1 in `test_scheduler.py`), all additions, no
removals:

- end-to-end (#1243): the configured scheduler producer path admits each due
  occurrence QUEUED (cursor advanced, node never run) and a second tick grows
  the backlog; `services.schedule_consumer.tick_schedule_consumer` drains
  exactly that backlog to COMPLETED through the real Container's canonical
  `execute_admitted_runs` seam (join the drain task it spawns)
- wiring: `EngineService.start` starts the consumer cadence (beside the
  legacy-DAG recovery cadence) and `EngineService.stop` joins it
- the cadence resolves the Container through the engine's AgentPort seam and
  answers None for the stub/demo port (no fabricated consumption)
- tick is a no-op without a wired container (no half tasks spawned);
  `consumer_disabled` reads the effective interval; a failing drain half does
  not silence the wake half across the decoupled tasks
- cadence mechanics: productive halves logged, one failing tick does not kill
  the loop, idempotent start keeps one task, disabled interval
  (`SCHEDULE_CONSUMER_INTERVAL_S <= 0`) starts nothing and warns loudly, stop
  cancels a tick in flight as a cancellation
- drain decoupling (#1260 Codex P1): while a claimed node runs long (drain
  blocked), later cadence iterations keep coming and the wake half keeps
  polling (≥2 wakes) with no second drain stacked; stop cancels and joins an
  in-flight drain task
- loop-honoring disable switch (#1260 Codex P1): `_ScheduleRunner._tick`'s
  canonical drain quiesces under `SCHEDULE_CONSUMER_INTERVAL_S <= 0` (same
  `consumer_disabled` predicate as the cadence) and drains again once the
  interval is positive

Verified +14 = collected across the two touched modules; every suite besides
`packages/hive-conductor/backend/tests` unchanged.
