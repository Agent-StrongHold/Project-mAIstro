---
inventory-delta:
  packages/hive-conductor/backend/tests: +32
---
# Conductor backlog board/list/detail over the canonical service (#99)

New file `packages/hive-conductor/backend/tests/test_backlog_routes.py` (36
node IDs; the note's delta is relative to the shared baseline, which already
carries the develop-side #99 rounds this branch merged) drives the new `/v1/backlog` surface over HTTP through the app, so
the canonical BacklogItem service (`services/backlog.py`, store
`stores.backlog_items`) is exercised on the shipped path, not a test seam.

Cases cover, by #99 acceptance criterion: list/board/detail payloads served by
the one canonical service (route mutations visible to the service; the
non-authoritative-until-#102 marker carried in every list/detail body);
optimistic concurrency (stale `expected_version` refused with 409 for every
mutation verb including decompose, current copy recoverable and re-applied);
inspection (dependencies resolved both directions, acceptance evidence,
source, provenance attributed per action and capped, risk, autonomy mode, goal
linkage); fail-closed authorization (anonymous 401 before the service,
strangers get the missing-id 404 — no existence oracle — workspace viewers
read but get 403 on every edit verb, editors succeed); and the lifecycle verbs
(block requires evidence, unblock clears it, reorder by priority-then-rank,
column moves, decompose links children, pin/pause/archive as durable operator
controls with archive hiding items until restored, archived items refusing
plain edits). Repair-round additions cover the detail-view visibility rule
(a caller's dependency summaries obey the same visibility rule as the item
itself — a private related item leaks nothing), the park-evidence rules
on the plain-edit and drag paths (no side door into blocked without a
reason; leaving blocked clears stale evidence), the copy-staging guarantee
(a refused patch leaves stored state untouched), and the creation-path
status legend check. No existing test was removed or renamed.
