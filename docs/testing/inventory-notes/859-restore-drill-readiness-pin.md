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
