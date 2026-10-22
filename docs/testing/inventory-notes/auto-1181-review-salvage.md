---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---
# auto-1181-review-salvage

Six tests added to `packages/hive-conductor/backend/tests/test_engine_startup_atomicity.py`
after the original #1181 note (`1181-engine-startup-atomicity.md`, +18): two
from the review rounds committed on this branch, four from the salvage round
that also hardened `services/engine.py`. No existing test was removed or
renamed.

- `test_sanitize_cause_redacts_credentials_before_truncation` and
  `test_sanitize_cause_fails_closed_without_the_redactor` (review rounds):
  the startup cause that reaches the unauthenticated `/health` is passed
  through the ADR-064 redactor before the 300-char truncation, and fails
  closed to the exception type alone if the redactor cannot be imported.
- `test_cancelled_boot_unwinds_cadences_and_reraises` (salvage): a boot task
  cancelled while awaiting `LocalTaskBackend.start()` still runs the full
  rollback — recovery cadences stopped, component handles cleared, instance
  `startup_failed`, attempt retained for `engine_health()`, singleton never
  published — because the rollback guard is `BaseException`, matching
  `CancelledError`'s base.
- `test_started_bridge_container_is_aclosed_on_later_step_failure` (salvage):
  a configured bridge that started is unwound by `reset_runtime_source()` +
  `Container.aclose()` (the pool lease / SQLite connections it took), not by
  dropping the reference — each retryable failure would otherwise take a
  fresh pool lease until the database runs out of slots.
- `test_in_flight_boot_reports_starting_not_not_started` (salvage): mid-boot,
  `engine_health()` answers `starting` — reachable only after `start_engine`
  began tracking the in-flight attempt (`_booting`) — and the marker never
  outlives the boot: after a cancelled attempt the snapshot reads
  `startup_failed`.
- `test_health_ready_gates_on_in_flight_boot` (salvage, contract-marked):
  `/health/ready`
  answers 503 with `checks["engine"]` false while a boot is mid-flight, per
  ADR-100126-f9d6's decision text, which lists `starting` among the
  not-ready states; liveness stays 200 `ok` with no cause yet.

Contract-marker follow-up (CI-repair round): the six tests above that pin
ADR-100126-f9d6's decision — `test_clean_boot_reports_ready`, the three
`test_health_ready_*` gating tests, `test_health_reports_degraded_engine_state`,
and `test_health_survives_engine_probe_failure` — now carry
`@pytest.mark.contract("behavioral")` (ADR-032's cross-check marker). The ADR
declares `contracts: [behavioral]` and lists this file in `tests:`, so the
markers are what make the claim evidenced instead of a new
`declared-kind-unproven` row in `quality/contract-markers-baseline.json`.
Test count is unchanged (+0): markers are annotations, not cases.

Companion production change in `services/engine.py`: the rollback contract
now covers `BaseException` (cancellation) at the sequence guard, at
`_start_task_backend`'s backend-start guard, and at `start_engine`'s
failed-attempt retention; the bridge unwind closes the container in addition
to resetting the materialization seam; and `start_engine` registers the
in-flight attempt so `engine_health()` can report `starting` instead of
conflating a slow boot with a process that never attempted one.

## Verification record (L1181 salvage round)

At the salvage head (branch `auto-1181`): `uv run ruff check .` clean,
`uv run ruff format --check .` clean (2670 files),
`pytest packages/hive-conductor/backend/tests/test_engine_service.py
packages/hive-conductor/backend/tests/test_engine_startup_atomicity.py -q`
→ 70 passed, and `check-suite-inventory.py` green after this note (3030).
