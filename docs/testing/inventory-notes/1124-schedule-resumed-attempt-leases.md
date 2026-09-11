---
inventory-delta:
  packages/maistro-core/tests: +3
---

The schedule resume regression adds one behavioral test in
`packages/maistro-core/tests/runs/test_parked_run_resume.py`. It drives a
scheduled node through its first pause, starts a resumed Attempt on each run
store backend, stops that Attempt's heartbeat as a worker-death simulation,
and runs the canonical recovery tick. The parameterized spine covers the
in-memory and SQLite stores unconditionally and PostgreSQL when its test DSN is
available; no schedule-private recovery path is introduced.
