---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/maistro-core/tests: +1
---

# 1248-registration-username-uniqueness

Added `test_independent_process_writers_publish_one_username` to
`test_registration_policy.py`. Two independent SQLite `State` writer processes
race the same username through the durable user-store insert; exactly one claim
wins and the database contains one user row. This covers the cross-process
failure mode that a process-local registration lock cannot protect. The state
suite also verifies that deleting a user releases its durable username claim.
