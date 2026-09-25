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

## Verification record (L1114 repair @ 26e6a2b8b08c, no code change)

Re-ran the battery at head `26e6a2b8b08ca8062248be982ed5f28700b23a11` with
`MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@127.0.0.1:21435/maistro`
(lane pg `auto-1114-pg2`, PG18): full `packages/maistro-core/tests/tasks/` =
**341 passed, 0 skipped, 0 failed** — including both PG crash-boundary tests
(`test_postgres_death_after_run_admission_executes_original_identity`:
admit -> injected process death -> bare recovery -> original run_id, exactly
1 NodeRun and 1 completed Attempt, Run COMPLETED; and its receipt-before-
notify sibling), the prior-finding proofs (`test_recovery_terminalizes_a_
running_claim_whose_node_run_has_no_attempt`, `test_postgres_lone_node_run_
is_not_stranded_claim_evidence`), and both malformed-admission terminal-
disposition tests. Without the DSN the same suite is 334 passed / 7 skipped.
`ruff check` clean; `ruff format --check` clean (2534 files); `mypy` on
`maistro/tasks` + `maistro/runs` clean (38 files); `check-execution-lifecycles`
OK (19 classified, no new lifecycle); `check-suite-inventory` ok (13 suites);
`maistro_server/tests/api/test_main.py` 17 passed (lifespan wiring calls
`queue.recover(container.run_store)`).

Correction to the record above: "every finding cites files this branch never
touched" is imprecise — 8 vulture-flagged paths do appear in the branch's
net diff (e.g. `maistro_server/main.py`, `maistro/reactor.py`). The
substantive claim survives inspection: every flagged identity in a
branch-touched file (`unhandled_exception_handler` main.py:482, `is_running`
reactor.py:74, `PgCanvasStore` store.py:162) exists verbatim on the develop
base 03c8ba83, and the branch's only `main.py` change is the 4-line
`queue.recover` wiring; the bulk of the NEW findings (fastapi-route-handler
in `hive-conductor/backend`) enters only via develop-side merge aec9e9166.
The vulture failure is develop-side drift against the ledger (authorized at
60862b6c5), not debt authored by this lane; no repair action taken here.
