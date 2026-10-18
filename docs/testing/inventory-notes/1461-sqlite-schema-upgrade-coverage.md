---
inventory-delta:
  packages/maistro-core/tests: +4
---
# 1461-sqlite-schema-upgrade-coverage

Four new tests in `packages/maistro-core/tests/persistence/test_sqlite_schema_upgrade.py`
cover the review-hardening paths added to `maistro.sqlite_schema` (relocated
from `maistro.persistence.sqlite_schema` in this PR — see the review-thread
fixes):

1. `test_busy_timeout_restored_after_upgrade` — the upgrade raises the
   connection's busy timeout while it runs and must restore the caller's
   value afterwards.
2. `test_busy_timeout_restored_after_failed_upgrade` — same restore on the
   exception path.
3. `test_commit_failure_rolls_back_and_propagates` — a failing `COMMIT`
   (reader in rollback-journal mode outlasting the busy timeout) must roll
   back instead of leaving the schema write lock held.
4. `test_sync_upgrade_restores_timeout_and_rolls_back_failed_commit` — the
   synchronous twin of (1)+(3), mirroring the guarantees on the sync path.

No production node IDs moved; the delta is purely added coverage for code
introduced by this PR.
