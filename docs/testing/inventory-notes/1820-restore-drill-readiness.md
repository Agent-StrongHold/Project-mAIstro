---
inventory-delta:
  tests/: +2
---
# 1820-restore-drill-readiness

CI-repair round for the Coverage gate failure at be901b83f (merge-queue
evaluation of #1820): the root-suite producer's
`test_real_verify_restore_drill_passes_end_to_end` failed on a shared runner
because `deploy/scripts/verify-restore.sh`'s 60-probe scratch-postgres
readiness budget expired under congestion (initdb outlived it), producing an
opaque VERIFIER FAIL for infrastructure, not for the backup under
verification. An unrelated branch's identical job failed in the same
10-minute window on a different timing-sensitive test, which is the
congestion evidence.

The repair widens the drill's readiness budget to 180 probes, adds a
liveness check that fails fast with the engine's last log lines when the
scratch container has exited, and confirms readiness with a real query
(`SELECT 1`) rather than pg_isready alone — pg_isready also answers during
initdb's temporary-server window, so a pg_isready-keyed loop can break
mid-init and the following restore fails as RESTORE instead of waiting out
the restart. The same probe hardening is applied to the characterization
module's own `_wait_ready`, which hit that exact race locally (CREATE TABLE
exit 2 immediately after a pg_isready pass) under a host congested by
dozens of leftover containers. Two node IDs are added to `tests/`
(test_backup_restore_oracle.py):

- `test_verify_drill_fails_fast_when_scratch_container_dies` — behavioral,
  hermetic (a fake `docker` shim, the same technique as the #1820
  install.sh harness): a scratch container that is already dead must yield
  VERIFIER FAIL naming the exit and carrying the engine's log, after few
  readiness probes (counted, not wall-clock-timed). Against the pre-change
  script this fails: no liveness check existed, the whole budget was burned,
  and the message blamed readiness.
- `test_verify_drill_readiness_budget_absorbs_a_loaded_runner` — pins the
  180-probe budget and the liveness check as script text, so a shrink back
  to ~60 probes fails review-time.
