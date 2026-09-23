---
inventory-delta:
  packages/maistro-core/tests: +19
---
# Pause-reason waker architecture test

Issue #1192 adds `packages/maistro-core/tests/graph/durable_runs/test_pause_reason_wakers.py`
(+19 collected node IDs, nothing removed or moved):

- 3 architecture assertions: every `PAUSE_RESUME_CONDITIONS` reason is either
  mapped to a production waker or listed in the strict `UNWOKEN` ledger; every
  mapped waker's entrypoint exists, has a non-test production caller, calls the
  canonical API it names, and that API accepts the status the reason parks in;
  every ledgered gap cites its issue.
- 11 self-tests proving those checks fail for the mutations they exist to catch
  (missing reason, deleted waker, ledgered reason that gains a waker, HITL
  answer aimed at a WAITING reason, timer aimed at an answer-gated reason,
  test-only caller, renamed entrypoint, unregistered route, a deadline only a
  manual route reaches, skipped API).
- 5 behavioural pins tying the declared
  accepted statuses to the shipped `answer_record`, `settle_hitl_record`, and
  `resume_due_graph_runs` eligibility, and the parked status to the executor.
