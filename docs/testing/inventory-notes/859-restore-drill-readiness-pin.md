---
inventory-delta:
  tests/: +1
---
# #859 repair — restore-drill scratch-Postgres readiness pin

Adds `test_scratch_readiness_probes_final_server_and_target_db` to
`tests/test_backup_restore_oracle.py`: the restore drill's scratch-Postgres
readiness wait must probe over TCP loopback (`-h 127.0.0.1`, unreachable for
the postgres image's socket-only temporary init server) with a real query
against the target database (unsatisfiable before `POSTGRES_DB` exists). The
fail-before half asserts the same property checker names violations on the
pinned pre-fix probe (`tests/fixtures/restore-readiness/racy-socket-probe.sh`),
so the pin cannot pass vacuously.

Context: at CI 61286a57cfdf the coverage-gate job's root-suite producer failed
with two live drill characterization cases
(`test_real_verify_restore_drill_passes_end_to_end`,
`test_semantic_loss_is_rejected`) racing the image entrypoint — the old socket
`pg_isready -U …` probe reported ready inside the temporary-server window,
producing `FATAL: database "maistro" does not exist` and
`FATAL: the database system is shutting down`. `verify-restore.sh` and the
characterization harness `_wait_ready` now probe the final server + target DB;
both previously-failing cases pass against real containers (20/20 in
`tests/test_restore_oracle_characterization.py` +
`tests/test_backup_restore_oracle.py` on the auto-859 host). No node was
removed or renamed; the only delta is the one added pin.

## Follow-up (union round, head bb93d6cd0)

Trunk independently landed a different fix for the same race
(`pg_isready` + socket `psql -d "${PG_DB}"`, test
`test_scratch_ready_means_the_target_database_answers`). The merge `6c5663de1`
took trunk's script while keeping this pin, which redded `test` and the
`Coverage gate`. `verify-restore.sh` now carries the **union** probe: the loop
requires `pg_isready` **and** a TCP-loopback `psql -h 127.0.0.1 -d "${PG_DB}"
-c 'SELECT 1'`, then `fail_verifier`s. Both landed tests pass on the one script;
the pin's assertions (`-h 127.0.0.1`, `SELECT 1`) and the fail-before fixture are
unchanged. See `.cursor/context/repair-859-union-readiness-round.md`.
