---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# homie1-1199-sqlite-deadline-fix-1aeb

PR #2512 / branch `homie1/1199-sqlite-deadline-fix`.

`packages/hive-conductor/backend/tests` +3 node IDs, all from one added test in
`test_schedule_projection_authority.py`:

- `test_a_failed_import_defers_the_row_repair_so_the_pending_edit_survives` —
  parametrized `[memory]`/`[pg]`/`[sqlite]` by the suite's `configured`
  fixture, hence one function = three node IDs.

The test pins behavior introduced by the same driver commit in
`services/schedule_projection.py`: a legacy row whose canonical import put
fails transiently must have its repair deferred (not rewritten from stale
canonical truth), so the row's newer pending Hive edit survives until the
retry succeeds. No tests were removed or renamed; collection at the parent
commit was 4511, matching the then-recorded expectation, and is 4514 after
this change.
