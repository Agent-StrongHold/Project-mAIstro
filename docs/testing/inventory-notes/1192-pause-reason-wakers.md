---
inventory-delta:
  packages/maistro-core/tests: +32
---
# Pause-reason waker architecture test

Issue #1192 adds `packages/maistro-core/tests/graph/durable_runs/test_pause_reason_wakers.py`
(+32 collected node IDs, nothing removed or moved):

- 4 architecture assertions: every `PAUSE_RESUME_CONDITIONS` reason is either
  mapped to a production waker or listed in the strict `UNWOKEN` ledger; every
  mapped waker's entrypoint exists, has a non-test production caller, calls the
  canonical API it names, accepts the status the reason parks in, and can
  select a Run that carries the reason (its admission builds a node kind that
  emits it); every reason parked beside a human pause is still released by one
  of the pair's wakers; every ledgered gap cites its issue.
- 16 self-tests proving those checks fail for the mutations they exist to catch
  (missing reason, deleted waker, ledgered reason that gains a waker, HITL
  answer aimed at a WAITING reason, timer aimed at an answer-gated reason,
  test-only caller, renamed entrypoint, unregistered route, a deadline only a
  manual route reaches, skipped API, due ticks that own no Run able to emit a
  timer reason, an answer whose drains own no human node, a mixed frontier only
  its timer could wake), plus the matching passing cases (a tick that owns an
  emitting node, a route that acts by run id).
- 12 behavioural pins: each `VIA_ACCEPTS` row equals what the shipped API
  accepts across every `RunStatus` (`answer_record`, `settle_hitl_record` for
  cancel, `expire_hitl_pauses`, `resume_due_graph_runs`,
  `recover_queued_graph_runs`), the parked status follows the executor's own
  frontier checkpoint (a timer beside a human pause parks PAUSED), and the
  admitted kinds and emitters read from the shipped modules.

A review found the first cut credited the legacy-DAG and Evolve due ticks as
wakers for the two elapsed-timer reasons, although neither admission can hold
a Jira or delegation node. Those reasons moved into the ledger, and the answer
route came out of the human reasons' wakers for the same reason: its drains
own only legacy and Evolve Runs.
