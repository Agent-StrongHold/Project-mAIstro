---
inventory-delta:
  packages/maistro-core/tests: +3
---
# Schedule transaction failure coverage

Adds three collected SQLite behavioral tests for the #1199 prerequisite
in PR #1304, in addition to the original +15 inventory delta.

- COMMIT raises before committing: roll back the uncommitted write and allow
  the next writer to complete.
- Cancellation during COMMIT: the transaction does not remain open after the
  connection's write lock is released.
- Cancellation after BEGIN has reached SQLite but before its await returns:
  roll back the begun transaction before another writer enters.

Each case reads the retained Schedule and then performs another successful
write through the same store and connection. The tests do not replace the
existing write-body failure, independent-connection, or lost-update cases.

PostgreSQL evidence clarification: the scheduling-directory conformance
cases run in the PostgreSQL coverage producer in quality.yml. They are not
collected by ci.yml's pg17/pg18 persistence-suite commands. No PostgreSQL
compatibility claim is made for a test merely because another PostgreSQL
job passed.
