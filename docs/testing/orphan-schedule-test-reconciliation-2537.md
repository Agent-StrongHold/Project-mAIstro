# Reconcile orphaned scheduling tests (#2537)

At develop 618954f, the root test_pg_store_coverage.py file contains 18
methods outside configured testpaths. The current Schedule model uses
runs_so_far, requires a cron/graph definition, and record_fire requires
next_due_at. The original tests cannot be moved as-is.

| Original method | Canonical equivalent or disposition |
| --- | --- |
| test_put_new_schedule | test_put_and_get_round_trip and test_put_on_a_new_row_stores_the_supplied_cursors; zeroing imported cursors is not the current contract |
| test_put_overwrites_existing | test_put_keeps_the_cursors_record_fire_wrote; retain stored cursors, not incoming stale values |
| TestPgScheduleStorePut.test_put_after_delete_restores_tombstone | New test_list_and_tombstone_follow_canonical_definition |
| test_list_all_returns_all_schedules | New test_list_and_tombstone_follow_canonical_definition |
| test_tombstoned_ids_returns_deleted_ids | New test_list_and_tombstone_follow_canonical_definition |
| test_list_all_excludes_deleted_schedules | New test_list_and_tombstone_follow_canonical_definition |
| test_record_fire_basic | test_record_fire_advances_the_cursor; explicit next_due_at |
| test_record_fire_max_runs_disables | test_disable_on_exhaustion_stops_the_schedule_being_due and test_serialized_fire_count_disables_after_concurrent_admissions |
| test_record_fire_nonexistent_returns_none | test_record_fire_on_unknown_schedule_returns_none |
| test_reserve_fire_basic | test_a_reservation_holds_the_run_without_spending_it |
| test_reserve_fire_nonexistent_returns_none | test_an_unknown_schedule_reserves_and_settles_to_none |
| test_reserve_fire_exhausted_returns_none | test_an_exhausted_schedule_cannot_be_reserved; raises ScheduleExhausted, not None |
| test_settle_pending_fire_success | test_a_confirmation_spends_the_run_and_disables_on_exhaustion |
| test_settle_pending_fire_nonexistent_returns_none | test_an_unknown_schedule_reserves_and_settles_to_none |
| test_settle_pending_fire_invalid_fire_id_returns_none | test_a_confirmation_without_a_marker_answers_none |
| test_delete_creates_tombstone | New test_list_and_tombstone_follow_canonical_definition |
| test_delete_nonexistent_returns_false | test_delete (second delete false) |
| TestPgScheduleStoreDelete.test_put_after_delete_removes_tombstone | New test_list_and_tombstone_follow_canonical_definition |

All named equivalents refer to packages/maistro-core/tests/scheduling/test_store.py.
The new scenario uses its existing memory/SQLite/PostgreSQL parity fixture.
Candidate 31de0a7, quality run 45959792559, PostgreSQL coverage job
140374642735: the new parity test passed on memory, SQLite and PostgreSQL.
CI job 140375077147 measured +3 core and +7 root node IDs. Based on that
source mapping and real PG evidence, this follow-up removes the stale root
file. The removal does not reduce collected node IDs. The revised candidate
must re-prove the complete suite and inventory.
