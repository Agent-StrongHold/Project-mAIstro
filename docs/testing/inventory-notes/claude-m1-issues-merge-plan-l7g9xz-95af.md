---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/maistro-core/tests: +19
---
# claude-m1-issues-merge-plan-l7g9xz-95af

Fixes the starvation defect shared by durable-run recovery, HITL-pause
expiry, and hive-conductor's `/v1/hitl/pending` scan: a bounded
oldest-first page combined with a post-hoc eligibility filter could let a
long ineligible prefix starve real work forever. All three now page
through a new `fair_page_scan` combinator instead of taking the first
page's worth of candidates as the whole answer.

`packages/maistro-core/tests` (+19): a new
`graph/durable_runs/test_fair_scan.py` suite covers `fair_page_scan`
directly (cursoring, short-but-nonempty pages, `max_inspected`/`limit`
stops); `test_recovery_wakeup.py`, `test_hitl_settlement.py`, and
`test_continuation_conformance.py` gained cases exercising the new
`after` cursor parameter across the in-memory, SQLite, and PostgreSQL
`DurableRunStore`/`GraphContinuationStore` backends, plus per-candidate
failure isolation in `recover_queued_graph_runs`/`resume_due_graph_runs`.

`packages/hive-conductor/backend/tests` (+1): `test_hitl_door.py` gained
a case covering the rewritten `/v1/hitl/pending` route's internal manual
paging against the same starvation scenario.
