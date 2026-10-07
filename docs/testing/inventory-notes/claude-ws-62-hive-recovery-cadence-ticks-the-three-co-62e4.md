---
inventory-delta:
  packages/hive-conductor/backend/tests: +10
---
# claude-ws-62-hive-recovery-cadence-ticks-the-three-co-62e4

+10 Hive backend tests, all new in `tests/test_canonical_recovery_cadence.py`
(#62). They prove the new `services/canonical_recovery.py` cadence ticks the
engine Container's three operator-scheduled recovery seams on a real SQLite
Container: an abandoned chat Attempt lease is reclaimed and its NodeRun parked
WAITING; a stranded chat admission is compensated CANCELLED; an elapsed
`RESUME_ON_ELAPSED` pause is resumed to COMPLETED; one failing half does not
silence the others or the loop; start is idempotent; stop drains the half in
flight instead of cancelling it, cancels only past the grace, returns when the
tick is cancelled elsewhere, and abandons a cadence left on a loop that is no
longer running; no Container means a no-op; and `EngineService.start`/`stop`
bracket the cadence. No test was removed or moved.
