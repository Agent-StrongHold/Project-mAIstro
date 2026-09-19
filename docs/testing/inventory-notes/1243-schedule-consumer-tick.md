---
inventory-delta:
  packages/hive-conductor/backend/tests: +10
---
# 1243-schedule-consumer-tick

Ten new tests in `packages/hive-conductor/backend/tests/test_schedule_consumer.py`
(1 async end-to-end failure-mode regression + 1 engine wiring + 8 cadence
mechanics), all additions, no removals:

- end-to-end (#1243): the configured scheduler producer path admits each due
  occurrence QUEUED (cursor advanced, node never run) and a second tick grows
  the backlog; `services.schedule_consumer.tick_schedule_consumer` drains
  exactly that backlog to COMPLETED through the real Container's canonical
  `execute_admitted_runs` seam
- wiring: `EngineService.start` starts the consumer cadence (beside the
  legacy-DAG recovery cadence) and `EngineService.stop` joins it
- the cadence resolves the Container through the engine's AgentPort seam and
  answers None for the stub/demo port (no fabricated consumption)
- tick is a no-op without a wired container; a failing drain half does not
  silence the wake half in the same tick
- cadence mechanics: productive ticks logged, one failing tick does not kill
  the loop, idempotent start keeps one task, disabled interval
  (`SCHEDULE_CONSUMER_INTERVAL_S <= 0`) starts nothing and warns loudly, stop
  cancels a tick in flight as a cancellation

Verified +10 = collected in the new module (10 passed); every suite besides
`packages/hive-conductor/backend/tests` unchanged.
