---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/maistro-core/tests: +6
---
# Issue 1240 — HITL workspace scoping

Adds one HTTP regression case covering listing, answering, and cancelling: a
principal with `dags.write` can only reach pauses in its canonical Workspace
membership set.

The follow-up +6 in `packages/maistro-core/tests` close the diff-coverage gate
the first wave opened: the durable stores grew a `workspace_id` filter on
`list_by_status`, and the SQLite durable-runs table has no such column — scope
lives on the canonical record (`record_json`), so the filter there reads it with
`json_extract`. Two store-level boundary cases (in-memory + SQLite, pinned
across the restart-safe schema) plus one spine-conformance case (all three
Run-store backends, PostgreSQL leg included) prove that a scoped listing
filters before paging and answers nothing for an out-of-scope Workspace.
