---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/maistro-core/tests: +49
---
# claude-m1-issues-merge-plan-l7g9xz-95af

Fixes the starvation defect shared by durable-run recovery, HITL-pause
expiry, and hive-conductor's `/v1/hitl/pending` scan: a bounded
oldest-first page combined with a post-hoc eligibility filter could let a
long ineligible prefix starve real work forever. All three now page
through a new `fair_page_scan` combinator instead of taking the first
page's worth of candidates as the whole answer.

`packages/maistro-core/tests` (+49): a new
`graph/durable_runs/test_fair_scan.py` suite covers `fair_page_scan`
directly (cursoring, short-but-nonempty pages, `max_inspected`/`limit`
stops, and — after the review finding that a per-tick bound restarting from
the top is the same starvation one size up — six `ScanContinuation` cases:
the reviewer's exact repro of a row behind the 2,000-row ceiling reached on
the next tick, the control row just inside it, resuming after the last
*inspected* row rather than the page, the restart from the top after walking
off the end, a stale position past the end, and a fetch failure leaving the
position untouched); `test_recovery_wakeup.py`, `test_hitl_settlement.py`,
and `test_continuation_conformance.py` gained cases exercising the new
`after` cursor parameter across the in-memory, SQLite, and PostgreSQL
`DurableRunStore`/`GraphContinuationStore` backends, plus per-candidate
failure isolation in `recover_queued_graph_runs`/`resume_due_graph_runs`;
`test_recovery_wakeup.py` also gained the multi-tick regression at the
production seam (more foreign-owned QUEUED Runs than one tick inspects, the
owned one reached on the second tick with a held continuation), and the new
`runs/test_fair_scan_parity.py` repeats that regression over the real keyset
paging of all three `RunStore` backends (three collected items; the
PostgreSQL leg runs where `MAISTRO_TEST_PG_DSN` is set).

`packages/hive-conductor/backend/tests` (+1): `test_hitl_door.py` gained
a case covering the rewritten `/v1/hitl/pending` route's internal manual
paging against the same starvation scenario.

A second review round found the same starvation one layer further down, at
the canonical store rather than at the combinator, and added 20 more cases
(+5 in `graph/durable_runs/test_fair_scan.py`, and a new
`graph/durable_runs/test_canonical_due_scan.py` whose five cases run against
all three continuation backends). `CanonicalDurableRunStore.list_due` reads a
page of due-index ids and drops the ones whose canonical Run has since gone
terminal, so a page made entirely of settled rows comes back empty — which is
also what the end of the index looks like. The walk read the two as the same
thing and reset to the top, so a settled prefix longer than one page hid the
live Run behind it on every tick. The new cases cover a fetcher reporting
progress and results separately (`ScanPage`), the inspection ceiling counting
dropped rows, exhaustion still restarting from the top, and — over the real
store on each backend — a hundred settled rows ahead of one genuinely due Run
being paged past in a single scan.
