---
inventory-delta:
  packages/maistro-core/tests: +7
---
# Issue 1114

Seven tests cover the restart-safe task admission contract: task payload fields
are committed on the queued Run, a new queue rehydrates and notifies from that
Run, both process-death gaps recover from the canonical Run, two rehydrated
receipts are fenced by the canonical transition, and a malformed payload is
terminalized visibly on the Run.

## Verification record (L1114 verify @ 57e7e79d0)

Independent re-run by the verifier at head `57e7e79d0c7f7838f89fa2a7482fcab44e15fc83`
with `MAISTRO_TEST_PG_DSN` pointed at the lane pgvector (127.0.0.1:21435):
`test_admission.py` + `test_issue_1114_repro.py` = 60 passed, 0 skipped — the
7 `pg_pool` tests executed for real (they skip without the DSN, as in the
driver's 70-passed/7-skipped run). Prior verifier finding (RUNNING Run with a
lone NodeRun and zero Attempts surviving `recover()`) re-proven fixed:
`test_recovery_terminalizes_a_running_claim_whose_node_run_has_no_attempt` and
`test_postgres_lone_node_run_is_not_stranded_claim_evidence` pass; a claimed
Run with Attempt evidence is left to the #232 sweep. Gates re-run: ruff check
(clean), ruff format --check (2534 files), suite inventory (core 10850,
server 369), server lifespan tests 17 passed, mypy on tasks+runs/admission
clean. Deltas across the five auto-1114 notes sum to 32, matching the counted
new tests. `scripts/check-vulture-baseline.py` fails monorepo-wide, but every
finding cites files this branch never touched (hive-conductor/evolve/rsi/
canvas/frontend); the baseline differs from develop only by the ensemble
`recover` prune, so the drift pre-exists on develop and is not this branch's
regression.
