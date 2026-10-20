---
inventory-delta:
  packages/maistro-core/tests: +4
---

Adds the durable (PostgreSQL) half of the duplicate-winner linkage residue (#1059 review, ported from the superseded #1282 branch onto develop's stores).

`test_pg_worker_killed_between_admission_and_record_fire` (parametrized over SKIP, BUFFER_ONE, CANCEL_OTHER) runs a real worker process that admits an occurrence on a live `PgRunStore`/`PgScheduleStore` and suspends inside an overridden `record_fire` checkpoint after the insert; the parent verifies the cursor never moved, SIGKILLs the worker so no compensation handler can run, and then re-admits from a fresh admitter: the surviving Run is linked into `last_run_id`, `already_fired` names the occurrence, and each overlap policy shows its observable contract on the next occurrence (SKIP consumes, BUFFER_ONE keeps the schedule due with the buffered occurrence unconsumed, CANCEL_OTHER reports `cancel_active_run` for the caller to act on).

`test_pg_replicas_converge_on_one_occurrence_and_schedule_pointer` races two admitters on two separate connection pools against one occurrence: exactly one Run exists, exactly one ticker reports the occurrence as already fired, and both replicas converge on the same winner in the occurrence index, the same schedule pointer, and `runs_so_far == 1`.

The suite requires a PostgreSQL test DSN (`pg_pool` fixture) and skips cleanly without one; the process-loss path is POSIX-only (SIGKILL).
