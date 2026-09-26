---
inventory-delta:
  packages/maistro-core/tests: +2
---

# auto-1114 durable-facts recovery repro

Two collected nodes in `tests/tasks/test_issue_1114_repro.py` (salvaged from a
timed-out repair pass, rewritten to run against the shipped recovery path),
reproducing the headline #1114 window at the strictest possible shape: the
durable QUEUED Run is committed through the production `TaskRunAdmitter.admit()`
write, and then every in-memory trace of the submission is discarded before
`TaskQueue.submit` could insert the receipt or enqueue the dispatch intent.

The restarted queue is deliberately bare — no admitter, no idempotency store,
no shared state, and the test hands it nothing but the Run store — so passing
proves recovery derives dispatchability from durable canonical facts alone:

- `test_a_run_with_no_living_receipt_is_recovered_from_durable_facts` — a
  bare `TaskQueue()` recovers the stranded Run: the receipt is rebuilt with
  the original `run_id`, QUEUED status and durable description, and the
  dispatch intent is re-enqueued.
- `test_recovered_dispatchability_is_anchored_on_the_canonical_run` — the
  recovery anchor is asserted on the durable side: `admission_source`,
  `task_id` and `task_payload` provenance on the QUEUED Run are exactly what
  the rehydrated receipt is rebuilt from, and an unknown task_id recovers
  nothing.

Both nodes pass in-memory; the same window on the durable store is owned by
`test_postgres_death_after_run_admission_executes_original_identity` in
`test_admission.py`.
