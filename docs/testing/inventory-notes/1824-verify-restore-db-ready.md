---
inventory-delta:
  tests/: +1
---

# #1824 CI repair: the restore drill must wait for the target database, not just a listening server

One node ID in `tests/test_backup_restore_oracle.py` (existing file):
`test_scratch_ready_means_the_target_database_answers`.

## Why

The merge-queue `test` job failed
`tests/test_restore_oracle_characterization.py::test_real_verify_restore_drill_passes_end_to_end`
(job 117798588381, head `94d199b11`) with:

```
pg_restore: error: connection to server on socket "/var/run/postgresql/.s.PGSQL.5432"
failed: FATAL:  database "maistro" does not exist
[verify-restore] RESTORE FAIL: pg_restore exited non-zero for backup 2026-10-18
```

— after the same test had passed earlier in the same job. The drill's scratch
readiness loop gated only on `pg_isready`, and `pg_isready` provably answers
"accepting connections" (exit 0) even when the requested database does not
exist (reproduced live: `pg_isready -U maistro -d nonexistent` → rc 0). The
postgres image entrypoint runs a temporary bootstrap server that accepts
socket connections before its init step creates `POSTGRES_DB`, so a poll
landing inside that window broke the loop and `pg_restore` raced into a
server without the database. The failure is intrinsic to the production
`deploy/scripts/verify-restore.sh` (the weekly cron drill is exposed to the
same race), not to the test.

## The fix and the pin

`verify-restore.sh` now additionally requires one successful
`psql -d "${PG_DB}" -c 'SELECT 1;'` before breaking the readiness loop, and
the post-loop guard fails closed into the existing VERIFIER failure class
when the target database never becomes ready. Failure classes, evidence
comparison, and security defaults are unchanged; `bash -n` still parses; the
oracle single-sourcing and no-`--restrict-key` pins still hold.

The new static pin rejects both the pre-#1881 fixture copy and a simulated
reversion to the pg_isready-only loop (verified locally), and passes on the
fixed script. The live characterization module
(`test_restore_oracle_characterization.py`, Docker) passes 4/4 runs after the
fix, the drill test three times in a row.

No other suite's count moves: the hive and server deltas in
`1824-model-config-runtime-reach.md` are unaffected.
