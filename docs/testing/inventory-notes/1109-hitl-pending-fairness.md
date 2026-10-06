---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
  packages/maistro-core/tests: +28
---
# 1109-hitl-pending-fairness

Issue #1109: pending HITL discovery must be fair instead of filtering after a
bounded PAUSED prefix. The fix is the pause-kind projection the issue asks for
by preference — `has_hitl_pause` on `GraphContinuation`, maintained on every
write beside the #1056 deadline projection, queried through
`DurableRunStore.list_hitl_paused` on all three backends (in-memory, SQLite,
PostgreSQL, the latter via migration 059) — plus one canonical bounded walk,
`pending_hitl_records`, that both consumers of pending discovery share: the
`/v1/hitl/pending` route and the Workspace Attention projection
(`services/attention.py`), which had duplicated the old filter-after-prefix
walk and now walks the projection with it.

## packages/maistro-core/tests: +28

`tests/graph/durable_runs/test_hitl_paused_index.py` is new: 28 collected node
IDs across the three-backend continuation fixture (projection claims only
PAUSED human rows, includes deadline-less pauses, pages on the created cursor,
filters by project), the canonical store (real executor-produced pause
discoverable, answered work leaves the projection, a stale projected row is
never disclosed, scope filters bind before disclosure, and a machine-only
PAUSED prefix longer than the limit cannot occupy the page — the mutation test
for `list_by_status(PAUSED, limit=N)` + in-memory filtering), the standalone
stores (same contract, plus SQLite reopen/backfill restart safety), and the
canonical walk itself (items-not-records bounding, multi-pause runs counting
per item, the membership recheck as the disclosure decision, Workspace-wide
vs named-Project scope, and the inspection ceiling).

## packages/hive-conductor/backend/tests: +3

`test_hitl_door.py` gains the HTTP-boundary regressions: a HITL pause behind a
machine-only prefix longer than the request inspection ceiling is still
returned (the ceiling must not become the starvation one size up), repeated
requests keep returning the same pending work (no consumed scan position, so
restart cannot make an item unreachable), and multiple human pauses on one Run
are returned individually and count individually against `limit`. The existing
two human pauses behind a `limit`-sized machine prefix and the offset-cursor
regressions keep pinning the request-scoped paging contract; the ceiling test
was rewritten to pin the bound that remains (a request stops) rather than the
starvation the projection removed.

Verified against a real PostgreSQL 18 server (`MAISTRO_TEST_PG_DSN`, migration
059 applied, and the 058 → 059 backfill exercised by planting a pre-059 row
and upgrading): the PostgreSQL parametrizations of the new suite pass, and
`packages/maistro-core/tests/graph/durable_runs` +
`packages/maistro-core/tests/runs` are green with the PG legs enabled
(2067 passed, 3 skipped).
