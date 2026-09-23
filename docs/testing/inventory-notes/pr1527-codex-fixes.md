---
inventory-delta:
  packages/maistro-canvas/tests: +16
---
# pr1527-codex-fixes

Codex posted 4 review findings on PR #1527 (Canvas job-runner/store canonical
convergence): 3 P1 concurrency/correctness bugs and 1 P2 shutdown-hang risk.
All 4 were real and fixed in `canvas/store.py`, `canvas/runner.py`, and
`canvas/composition.py`. This note covers the +16 new tests added to cover
those fixes — no tests were removed or renamed net-zero; two existing tests
were rewritten in place to match a changed contract (see below), which is
why the net delta is smaller than a simple sum of new test functions might
suggest.

- **`tests/test_canvas_store_job_lease.py`** (+9): direct `PgCanvasStore`
  coverage for `update_job`'s new `expected_leased_by` fencing parameter
  (matched write succeeds; mismatched write raises `JobLeaseLostError`;
  gone-row still raises `JobNotFoundError`), the new `renew_lease` heartbeat
  method (extends on match, no-op `False` when not held, rejects
  non-positive durations), and `reap_expired_leases`'s split two-phase
  UPDATE (requeue-with-budget vs. clear-lease-only-stay-running for
  exhausted candidates). One pre-existing test
  (`test_reap_expired_leases_returns_empty_list_when_none_expired`) was
  updated in place: the method now issues two UPDATE statements before the
  empty check, not one, so its fake `AsyncSession` needed a second canned
  empty result.

- **`tests/test_job_runner_lifecycle.py`** (+4 net: 6 new, 2 rewritten in
  place): covers the runner-level half of the same 3 P1 findings — a stale
  worker's completion write is discarded (not clobbering a reclaiming
  worker's state) when its fenced `update_job` call loses the race; a
  provider call that outlasts one lease window gets renewed by a background
  heartbeat; an exhausted-retry job only reaches `FAILED` after canonical
  `fail_job_execution` reconciliation actually succeeds, and stays
  `running`/reconcilable if that call raises instead of being terminalized
  early. The in-memory `InMemoryJobStore` test double was changed to return
  independent copies of each job from every read (`claim_next_pending`,
  `get_job`, `reap_expired_leases`) rather than the same shared mutable
  object — the previous shared-reference design would have silently masked
  the exact stale-write races these findings are about. One existing test
  (`test_dead_worker_lease_fails_when_budget_exhausted`) was rewritten as
  `test_dead_worker_lease_at_exhaustion_stays_running_not_yet_terminal` to
  match the new two-phase contract (store leaves it `running`; only the
  runner's `reap_once` terminalizes it, and only after reconciliation).

- **`tests/test_canvas_runner_shutdown.py`** (new file, +4): covers the P2
  finding — `bind_canvas_runner_lifecycle`'s shutdown handler now bounds its
  wait for a stuck runner task with `shutdown_timeout` and cancels it rather
  than awaiting unconditionally forever. Tests cover the stuck-task
  cancellation path, the ordinary graceful-stop path (never cancelled), a
  duplicate startup call, and a shutdown call with no prior startup.

- **`tests/test_canonical_executor_integration.py`** and
  **`tests/test_migration_parity.py`**: no net new tests, but their own
  `CanvasStore` test doubles (`_CanvasStore`, `_SingleJobStore`) needed
  `update_job`'s new `expected_leased_by` parameter added (with real
  fencing behavior, not just accepted-and-ignored) since the runner now
  always passes it on its completion write; one test in the former file
  (`test_runner_idle_and_reap_terminal_failure_paths`) was updated to seed
  its reaped fixture job as `running` rather than pre-set `failed`, matching
  the same two-phase reconciliation contract.
