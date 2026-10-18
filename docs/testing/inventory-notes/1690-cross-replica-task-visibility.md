---
inventory-delta:
  packages/maistro-core/tests: +23
  packages/maistro-server/tests: +2
---

Closes the cross-replica task-visibility gap (#1690): `GET /v1/tasks/{id}`,
`GET /v1/tasks/{id}/result` and `DELETE /v1/tasks/{id}` no longer answer only
from the accepting replica's in-process `TaskQueue`.

`packages/maistro-core/tests` (+23) splits across four files:

- `tests/runs/test_find_run_by_task_id.py` (+4) — the new
  `find_run_by_task_id` store read answers identically on all three backends
  (in-memory scan, SQLite `json_extract`, PostgreSQL JSONB provenance
  expression; the PostgreSQL leg skips without `MAISTRO_TEST_PG_DSN`), a
  foreign `admission_source` filter does not answer a task receipt id, a miss
  is a plain `None`, and the test's own assumption that the foreign source is
  the chat admission source is pinned.
- `tests/tasks/test_cross_replica_receipt_reads.py` (+18) — two `TaskQueue`
  "replicas" over one shared canonical Run store and one shared durable
  TaskRecord sink, no in-memory state in common: a replica that never admitted
  the task answers `get_shared` with the same receipt identities (including
  when the fire-and-forget TaskRecord write has not landed — the SIGKILL
  case, answered from the Run alone); the landed row serves a replica on its
  own; a foreign principal gains nothing through either durable source;
  terminal Run truth converges the projection and a stale durable success
  over a failed Run is not resurrected; a non-terminal Run caps a
  terminal-claiming row at not-done (the stale row replaces the landed one in
  place, so the demotion branch is exercised deterministically); cancellation
  works from a replica holding no receipt, through the same canonical Run
  authority, with the owning replica's refused transition reconciling its
  projection; a claim-lost dispatcher's dropped receipt reads the winner's Run
  truth; a read with no durable source is a plain miss; a malformed run
  payload answers nothing; an admitter store outage degrades to the durable
  row verbatim; a queue with no admitter and an admitter predating the finder
  degrade the same way; the pure owner rule (provenance user_id, else the
  task payload's, else none) is pinned; an ownerless Run is visible only to
  empty scoping; `cancel_shared`'s local half is `cancel` unchanged; and a
  durable receipt with no Run behind it is refused cancellation rather than
  fabricated an anchor; the projection pins the Run identity over a
  disagreeing row; and the provenance read is scoped to the task queue's own
  admission source.
- `tests/tasks/test_workspace_routing.py` (+1) — the workspace-routing
  admitter resolves a task receipt id through its default binding, the same
  Workspace-independent way it resolves a run id.
- `tests/tasks/test_admission.py` (±0) — the duplicate-delivery loser now
  asserts its unauthoritative receipt is dropped (reads fall through to the
  durable projection) instead of parked stale in memory; same node count.

`packages/maistro-server/tests` (+2) — `test_task_cross_replica_visibility.py`
is the two-process durable composition the issue requires: real
maistro-server subprocesses over one migrated PostgreSQL, requests alternated
across their ports the way the load balancer alternates across replicas. The
first test covers the full failover arc — a task admitted through replica A
read back through replica B (which never saw the POST), replica A SIGKILLed
while the task is still QUEUED with the receipt remaining queryable, two fresh
replicas recovering and racing the same task with the canonical consumer claim
deciding a single owner (one execution, one NodeRun, one Attempt on the
spine), load-balanced polling answering 200 through every door until terminal,
and an idempotent resubmission replaying the original admission (#1176)
without executing again. The second pins authorization end to end: a foreign
authenticated principal gets 404s on every read shape through the durable tier
and the per-replica listing never leaks the task. Both skip without
`MAISTRO_TEST_PG_DSN`.
