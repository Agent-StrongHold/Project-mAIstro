---
inventory-delta:
  tests/: +2
---
# auto-448-ci-repair-56a8cec3

Lane L448 (issue #448) CI repair at 56a8cec33. The Coverage gate
(publish-set floor + diff coverage) failed in the `combine` step, not at
either floor: the root-suite producer (`--source=scripts`) died with 4
errors in `tests/test_restore_oracle_characterization.py`
(run 39144525906, job 117729747048). Every module-scoped fixture errored at
its first `CREATE TABLE` with `psql ... returned non-zero exit status 2`
(connection went bad) — after `_wait_ready`'s `pg_isready` probe had passed.

## Root cause (proven live, not inferred)

`pg_isready` answers 0 while the official postgres image's *temporary*
initdb server is still accepting connections — before the `maistro`
database exists and before the real server replaces the temporary one. A
high-frequency probe against `pgvector/pgvector:pg17` caught the window:
`pg_isready` green at t=0.63s, then `FATAL: database "maistro" does not
exist` (t=0.69s), `FATAL: the database system is starting up` (t=0.77s),
socket gone during the restart (t=0.85s), statement path green at t=0.95s.
psql connection-fatal errors exit 2 — the exact CI signature. The old
`_wait_ready` (60 × `pg_isready` at 1s) concluded readiness from the socket
ping, so the fixture's first statement raced the restart.

## Fix and evidence

- `_wait_ready` now polls the statement path itself (`psql ... SELECT 1`),
  keeps the hardened `verify-restore.sh` budget (120 × 1s), fails fast with
  `docker logs` once the container has exited, and only concludes on a
  successful statement. This is the same two-direction readiness repair the
  branch already applied to `verify-restore.sh` at 4265f5106 (slow-initdb);
  this closes the ready-too-early direction.
- All 4 characterization tests pass against the real image (3 consecutive
  runs, docker), and the full root-suite producer now completes:
  `pytest tests/ tests/test_model_check_consumer_claim.py
  packages/maistro-core/tests/extensions/test_lifecycle_proof.py` →
  **5381 passed, 135 skipped, 0 errors** (CI at 56a8cec33: 5377 passed,
  135 skipped, 4 errors).

## tests/ (+2)

Two pinning tests for the wait's decision rule (the four characterizations
only exercise a healthy image, so none of them fails if the wait regresses
to the socket ping):

- `test_wait_ready_concludes_on_the_statement_path_not_pg_isready` — fake
  `subprocess.run` where two statement probes fail (`the database system is
  starting up`) and the third succeeds; the wait must return only via that
  path. Any `pg_isready` reaching the fake raises, so the test fails against
  the old implementation (proven: the old body, exec'd from git HEAD,
  returned after one `pg_isready` poll with zero statement probes).
- `test_wait_ready_fails_fast_with_logs_when_the_container_exited` — an
  exited container must surface its logs and stop probing instead of burning
  the budget.

The publish-set floor (87%) is unaffected by this change — `tests/` is the
`scripts` producer, outside the publish set — and passed at this head in CI
(TOTAL 94% over the combined 84019-statement report). The diff-coverage
step was locally reproduced over the branch's changed files: 12 changed
files measured, 11 pass both floors; `sandbox/backends/bubblewrap.py:313`
(the truncation-warning branch) is uncovered **on this host only** because
`detect_host_capabilities()` refuses bubblewrap here (`Creating new
namespace failed: Resource temporarily unavailable`) and skips
`test_bubblewrap_backend_truncates_beyond_config_limit` — CI's coverage-unit
run installed bubblewrap and lifted the userns restriction
(`sysctl kernel.apparmor_restrict_unprivileged_userns=0`), ran it, and
passed 26 more core tests than this host (15421/1048 vs 15395/1074), so the
line is covered in CI's measurement.
