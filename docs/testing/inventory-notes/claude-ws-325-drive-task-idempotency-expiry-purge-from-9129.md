---
inventory-delta:
  packages/maistro-core/tests: +22
---
# claude-ws-325-drive-task-idempotency-expiry-purge-from-9129

`packages/maistro-core/tests/tasks/test_idempotency_purge_driven.py` is new
(#325): the claim path now drives `purge_expired`. Six tests run on each of
the three claim-store backends (in-memory, SQLite on a temp file, PostgreSQL
when `MAISTRO_TEST_PG_DSN` is set), for 18 node IDs. They check that:

- a later claim purges expired claims;
- the purge stops at its limit;
- a full batch makes the next claim purge again, until the backlog is gone;
- a claim inside the interval does not purge again;
- a new store waits one interval before its first purge;
- a failing purge never fails the claim.

Three tests are in-memory only. One checks that a purge already running is
not joined. One checks that a claim cancelled mid-purge leaves no pending row.
The third goes through `TaskQueue.submit`, the POST /tasks path, to show that
admission alone purges the table. One PostgreSQL-only test checks that a purge
does not delete a claim another connection renewed while the purge waited on
its row lock. That makes 22 node IDs in all. Nothing was moved or removed.
