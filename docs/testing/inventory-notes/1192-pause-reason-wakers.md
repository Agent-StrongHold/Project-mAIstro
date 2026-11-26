---
inventory-delta:
  packages/maistro-core/tests: +33
---
# Pause-reason waker architecture test

Issue #1192 adds `packages/maistro-core/tests/graph/durable_runs/test_pause_reason_wakers.py`
(+33 collected node IDs, nothing removed or moved):

- 4 architecture assertions: every `PAUSE_RESUME_CONDITIONS` reason is either
  mapped to a production waker or listed in the strict `UNWOKEN` ledger; every
  mapped waker's entrypoint exists, has a non-test production caller, calls the
  canonical API it names, accepts the status the reason parks in, and can
  select a Run that carries the reason (its admission builds a node kind that
  emits it); every reason parked beside a human pause is still released by one
  of the pair's wakers; every ledgered gap cites its issue.
- 17 self-tests proving those checks fail for the mutations they exist to catch
  (missing reason, deleted waker, ledgered reason that gains a waker, HITL
  answer aimed at a WAITING reason, timer aimed at an answer-gated reason,
  test-only caller, renamed entrypoint, unregistered route, a deadline only a
  manual route reaches, skipped API, due ticks that own no Run able to emit a
  timer reason, an answer whose drains own no human node, a mixed frontier only
  its timer could wake), plus the matching passing cases (a tick that owns an
  emitting node, a route that acts by run id, a tick handed to its loop by
  reference).
- 12 behavioural pins: each `VIA_ACCEPTS` row equals what the shipped API
  accepts across every `RunStatus` (`answer_record`, `settle_hitl_record` for
  cancel, `expire_hitl_pauses`, `resume_due_graph_runs`,
  `recover_queued_graph_runs`), the parked status follows the executor's own
  frontier checkpoint (a timer beside a human pause parks PAUSED), and the
  admitted kinds and emitters read from the shipped modules.

A review found the first cut credited the legacy-DAG and Evolve due ticks as
wakers for the two elapsed-timer reasons, although neither admission can hold
a Jira or delegation node. Those reasons are now woken by #837's
registered-DAG due tick, and the HITL answer's drains include its queued
recovery half.
