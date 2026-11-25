---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# 1064-latest-snapshot-restore

Adds `test_latest_admission_snapshot_supersedes_older_committed_snapshot` to
prove that restart restoration selects the newest Evolve publication boundary.
A cycle's later admission snapshot is the compensation base for that cycle;
restoring an older committed snapshot drops members admitted since the prior
cycle and can make recovery reject or execute against stale membership.
