---
inventory-delta:
  packages/maistro-canvas/tests: +3
---
# pr1535-runner-diff-coverage

Three new tests in `packages/maistro-canvas/tests/test_job_runner_lifecycle.py`
cover `CanvasJobRunner` paths that PR #1535 changed but no test exercised:

- `test_reap_once_leaves_requeued_jobs_alone` — a reaped job with retry budget
  left comes back `pending`; `reap_once` must neither reconcile it canonically
  nor terminalize it.
- `test_reap_once_without_canonical_hook_fails_with_lease_expiry_reason` — an
  executor without `fail_job_execution` still terminalizes an exhausted receipt,
  with the lease-expiry reason and cleared lease fields.
- `test_lease_renewal_heartbeat_survives_a_failing_renew` — a renew that raises
  is logged and never aborts the in-flight provider call.

No tests were removed or moved; the delta is exactly these three additions.
