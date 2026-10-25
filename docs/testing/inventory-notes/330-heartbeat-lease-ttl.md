---
inventory-delta:
  packages/maistro-core/tests: +0
---
# 330-heartbeat-lease-ttl

Zero test-count delta. One existing test changed a constant: the lease TTL in
`packages/maistro-core/tests/runs/test_parked_run_resume.py::test_a_resumed_schedule_attempt_is_leased_and_reclaimed_after_worker_death`
moved from 0.5s to 5s (identity, parametrization `[memory, sqlite, postgres]`,
and assertion set unchanged — the suite counts at 44 collected / 43 passed + 1
skipped are identical before and after).

**Why a constant change is the repair.** This test flaked red on the
`coverage (no services)` job at head `aa1581274` (run 40142381555, job
121016624638): "a live resumed Attempt was not renewed by the heartbeat" on the
sqlite leg. The poll budget was not the problem — all 150 iterations completed
inside the 30s pytest timeout, so the loop was turning, yet no renewal was ever
visible. The heartbeat ticks at ttl/3 (~0.167s with ttl=0.5s), and its first
tick landing after the expiry boundary is refused by
`renew_attempt_lease` (lapsed leases may not be resurrected,
`runs/lifecycle.py`), which stops the heartbeat permanently — correct
production behavior for a worker silent past its TTL, fatal for a test whose
lease is shorter than a loaded, coverage-instrumented runner's scheduling
latency.

**Reproduction (throwaway harness, not committed).** Replaying the test's
renewal-poll section with a 1s `time.sleep` loop stall injected right after the
resumed node starts fails with the exact CI error at ttl=0.5s (memory and
sqlite legs) and passes the same stall at ttl=5s. 5s keeps the first tick at
~1.7s, far inside the lease, while the recovery tick's explicit clock
(`now=live_lease.expires_at + 1µs`) keeps the expiry/reclaim boundary exactly
as deterministic as before.

The `coverage (no services)` cascade this closes: coverage-unit red ⇒
`Coverage gate (publish-set floor + diff coverage)` skipped (it `needs`
coverage-unit) ⇒ `gates-ran` red ("present but did not execute to a verdict").
The docker-pull `::error::` line in the same CI log is a red herring — the
image pull succeeded on that run; the quoted line is the step's script echo.
