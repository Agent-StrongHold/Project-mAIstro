---
inventory-delta:
  packages/maistro-bootstrap/tests: +2
---
# auto-448-ci-repair-4265f510

Lane L448 (issue #448) CI repair at 4265f5106: the `test` job failed in
`tests/test_restore_oracle_characterization.py` (scratch postgres never
became ready — runs 39116394628 and 39134762935, two different tests of the
same module) and the Coverage gate failed on
`maistro_bootstrap/builders/container_sandbox.py` (75% of 8 changed branch
arcs, partial at the `read_file` exit/timeout conditions).

## packages/maistro-bootstrap/tests (+2)

- `test_container_sandbox_output_bound.py` — `read_file` now checks
  `run.timed_out` before the exit status: `run_bounded` kills a timed-out
  child, whose nonzero exit status was previously misread as
  `FileNotFoundError` (the branch's declared timeout error was unreachable).
  New tests: a failing `cat` raises `FileNotFoundError`, and a read that
  outlives its bound raises the timeout `RuntimeError`, not
  "missing file" (this test fails against the old ordering — reproduced).

## tests/ (+1, absorbed by an already-banked delta)

- `test_backup_restore_oracle.py::test_verify_readiness_failure_is_diagnosable`
  pins the verify-restore.sh readiness repair: on a readiness failure the
  drill must consult the container's state (fail fast once it has exited),
  surface `docker logs`, and carry the widened 120-probe budget.

The root-suite ledger is deliberately NOT incremented for that test. This
branch carried a latent −1 drift on `tests/` (expected 5505, collected 5504
at 4265f5106; invisible in CI because the `test` job died on the restore
oracle before the inventory step ever ran), banked as `tests/: +1` in
`auto-448-develop-sync-inherited-drift.md` when it presented as a +1. The
new test occupies exactly that slack: expected 5505 == collected 5505 with
no new delta. Recording +1 here would double-count it and reverse the drift.
