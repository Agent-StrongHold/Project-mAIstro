---
inventory-delta:
  packages/maistro-core/tests: +17
---
# claude-ws-325-drive-task-idempotency-expiry-purge-from-9129

`packages/maistro-core/tests/tasks/test_idempotency_purge_driven.py` is new
(#325): the claim path now drives `purge_expired`. Five tests run on each of
the three claim-store backends (in-memory, SQLite on a temp file, PostgreSQL
when `MAISTRO_TEST_PG_DSN` is set), for 15 node IDs. They check that a later
claim purges expired claims, that the purge stops at its limit, that a claim
inside the interval does not purge again, that a new store waits one interval
before its first purge, and that a failing purge never fails the claim. Two
more tests are in-memory only. One checks that a purge already running is not
joined. The other goes through `TaskQueue.submit`, the POST /tasks path, to
show that admission alone purges the table. Nothing was moved or removed.
