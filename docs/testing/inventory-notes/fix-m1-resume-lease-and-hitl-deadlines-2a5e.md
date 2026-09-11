---
inventory-delta:
  packages/maistro-core/tests: +13
---
# fix-m1-resume-lease-and-hitl-deadlines-2a5e

Fixes two related M1 defects: resumed chat/graph Attempts never inherited
`lease_ttl`, so a crash mid-resume left them permanently unreclaimable
(#1112/#1124); and a HITL node re-pausing on a malformed answer recomputed
`now + timeout_seconds` instead of reading back the durable deadline
`answer_record` had already stamped onto it, letting repeated bad answers
extend a canonical approval window indefinitely (#1097).

`packages/maistro-core/tests` (+13): a new `runs/test_schedule_resume_lease.py`
crash-injection suite covers `ScheduleAttemptExecutor` forwarding
`lease_ttl` into `RunExecutionService` so a resumed Attempt is reclaimable
after a crash. `graph/nodes/test_human_verdict_fail_closed.py` gained
cases for the new `preserved_hitl_deadline()` helper across all three HITL
verdict nodes (malformed-answer-preserves-deadline, first-pause fallback,
repeated-malformed-answers-don't-extend, and pause evidence present but
without a usable `resume_at`). `graph/durable_runs/test_hitl_settlement.py`
gained end-to-end cases driving a real `human.approve_draft` node through
`run_durable_graph`/`resume_durable_graph` and checking `hitl_deadline()`.
