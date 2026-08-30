---
inventory-delta:
  tests/: +10
---
# chatgpt-merge-queue-base-resolution-refresh-39b1

Closes the diff-coverage gap this branch's own changes to
`scripts/check-ac-state.py` and `scripts/ci_merge_group_scope.py`
exposed: 2 new node IDs in `tests/test_ac_state_merge_guard.py`
(`_actual_base_revision`'s delegation to the shared resolver, and
`main()`'s `BaseRevisionError` handling) and 4 in
`tests/test_ci_merge_group_scope.py` (the `durable_events` and
`strike_ladder` classification branches, plus the CLI entrypoint's
plain and `--json` output). No existing test moved or was removed.

A second round, fixing four real classifier gaps a Codex review of this
PR found in `scripts/ci_merge_group_scope.py`, adds 4 more node IDs:
`alembic.ini` was invisible to both the `postgres` and `docker_build`
legs (it sits outside the `alembic/` prefix those checks looked under);
a migration file with `durable`/`event` in its name skipped the
`durable_events` leg entirely, because that check was gated on `core`
paths only; and any `packages/maistro-core` change left `hive_e2e`
false even though Hive imports and ships `maistro-core` in its E2E
image. `test_archive_change_runs_minio_wheel_and_docker_only` is
renamed to `test_archive_change_runs_minio_wheel_docker_and_hive_e2e`
and its `hive_e2e` assertion flips from `False` to `True` to match the
corrected behavior — a rename, not a net-new node ID. The four new IDs
are `test_alembic_ini_runs_postgres_and_docker`,
`test_durable_events_migration_runs_durable_events_leg`,
`test_core_only_change_runs_hive_e2e_too`, and
`test_root_file_outside_every_prefix_skips_docker_build_too` (closing
a branch-coverage gap the fix itself introduced: no existing case left
`docker_build` false, since every prior path fell under some prefix in
that leg's allowlist).
