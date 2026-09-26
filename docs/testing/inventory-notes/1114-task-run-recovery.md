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

## Verification record (L1114 independent review @ 3100784349)

Fresh independent review at head `3100784349c4b72f08be5521ffa38abd3aa104fc`
(develop base 03c8ba83), redoing the prior round whose worker died before it
could emit a result. Prior finding (RUNNING task Run with a lone NodeRun and
zero Attempts surviving `recover()` as immortal, reproduced at 54defd05ad)
re-attacked from scratch with a standalone driver written outside the repo
(`/tmp/verifier_1114_repro.py`): forced RUNNING + `create_node_run` + zero
Attempts on both `ClaimingInMemoryRunStore` and `ClaimingPgRunStore` (lane pg
`auto-1114-pg2`, 127.0.0.1:21435) — `recover()` now fails the Run visibly
(`task_recovery_failed: running task Run has no physical execution evidence`),
leaves the NodeRun as evidence, and stays FAILED across a second restart; a
claimed Run with a real Attempt stays RUNNING for the #232 sweep. The fix is
`71f683441` (evidence test is the Attempt, not the NodeRun).

Batteries executed at this head:
- `packages/maistro-core/tests/tasks/` without DSN: 334 passed, 7 skipped
  (matches the driver's check-3 shape); with
  `MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@127.0.0.1:21435/maistro`:
  **341 passed, 0 skipped** — all seven PG tests ran for real, including both
  #1114 crash boundaries (death after `admit()` returns; death after receipt
  before `_pending.put`), death between dispatch phase and claim, both
  terminal-disposition tests, and original-identity execution (original
  run_id, 1 NodeRun, 1 completed Attempt, Run COMPLETED).
- PR paths (`test_admission.py`, `test_issue_1114_repro.py`,
  `test_main.py`) with DSN: 77 passed.
- Gates re-run by this reviewer: `ruff check .` clean;
  `check-suite-inventory` ok for core and server suites;
  `check-execution-lifecycles` OK (19/19 classified, no new vocabulary);
  mypy on `maistro/tasks` + `maistro/runs` clean (38 files). Driver logs
  check-0..check-5 (uv sync, ruff check, ruff format, pytest, inventories)
  all pass at this head.

Acceptance walkthrough (all proven by executed tests above): durable payload
on the QUEUED Run (`TASK_PAYLOAD_KEY` committed in the same `admit_direct_work`
write — admission.py:185-208; `test_the_run_contains_the_restart_payload`);
recovery from durable facts alone (`test_a_run_with_no_living_receipt_is_
recovered_from_durable_facts`, bare queue, Run store only); original
identity chain (in-memory + PG crash tests); duplicate-recovery fencing
(`test_two_recovery_receipts_have_one_canonical_transition_winner`,
`test_a_duplicate_delivery_loses_the_claim_without_touching_the_winner`,
`test_recovery_yields_the_run_a_worker_already_claimed`, runner
`ConsumerClaimLost` disposition); visible terminal disposition for malformed
admissions; TaskRecord stays a best-effort receipt while the Run provenance
supplies all execution input; no second lifecycle (lifecycles gate + recovery
reuses canonical Run store/claim/Attempt semantics). Stop condition respected:
the fix is restart-safe reachability from durable admitted facts, not polling
or killing live work.

Closure-keyword audit: 0 `fixes/closes/resolves` matches in branch commit
subjects and bodies; PR #1488 body (snapshot) says only "Refs #1114".
`check-vulture-baseline.py` fails monorepo-wide (rc=1, 1447 findings) but
zero findings touch this branch's changed surfaces (`maistro/tasks`,
`maistro/runs/admission`, server main) — the pre-existing develop-side drift
documented above, not this lane's debt.

## Verification record (L1114 repair @ a994af1447, develop sync + re-validation, no code change)

The previous round's evidence was rejected only because the worktree moved
during verification (docs commit `6a2c6026c` landed on top of the reviewed
`310078434`); no code defect was found. This round resolved the lane's
develop drift (`origin/develop` had `5eeac0734` compliance-evidence gating +
`2c8022fe8` buildx bump; no conflicts with lane surfaces) by merging
`origin/develop` into `auto-1114` at `a994af1447c3`, then re-ran the full
battery at that merged head with
`MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@127.0.0.1:21435/maistro`
(lane pg `auto-1114-pg2`, PG18, `alembic upgrade head` at head):

- `packages/maistro-core/tests/tasks/` = **341 passed, 0 skipped, 0 failed**
  — both crash boundaries (`test_postgres_death_after_run_admission_
  executes_original_identity`, `test_postgres_death_after_receipt_before_
  notification_executes_original_identity`) and the stranded-claim PG tests
  executed for real; `-k postgres` alone = 7 passed, 0 skipped.
- Targeted trio (`test_admission.py`, `test_issue_1114_repro.py`,
  `test_main.py`) = 77 passed.
- Independent standalone PG probe (driver kept outside the tree,
  `probe_1114.py` in the job directory) replayed the prior finding's exact
  state — task Run forced RUNNING with one NodeRun and zero Attempts — on
  `ClaimingPgRunStore`: `TaskQueue.recover()` terminalizes it to FAILED with
  `task_recovery_failed: ... stranded dispatch`, `recovered=0`, and a second
  restart leaves it FAILED (idempotent, never immortal). PROBE: PASS.
- Gates at the merged head: `ruff check .` clean; `ruff format --check .`
  2546 files clean; `check-suite-inventory` ok for core and server;
  `check-execution-lifecycles` OK 19/19; mypy (full six-package set from
  AGENTS.md) Success in 713 files; `check-vulture-baseline.py` **rc=0**
  after the develop merge (prior monorepo drift is gone upstream) with zero
  lane-surface findings; the develop-merged `check-compliance.py` reports
  the registry and COMPLIANCE.md valid.

The prior finding remains fixed at this head (fix `71f683441`: a lone
NodeRun is not stranded-claim evidence; Attempt presence decides). No
source changes were needed this round; the only tree delta is this note and
the develop merge.

## Verification record (L1114 independent review @ 8bf0263c411b, second develop sync)

Fresh independent verification at head `8bf0263c411b4a23f026dafb08d21d752ccc7260`
(the round after `a994af1447`: merge of develop `55c5ad892` — M1-B8 HITL waiting
NodeRuns — into `auto-1114`). The previous round's evidence was rejected only
because the worktree moved (develop sync); no code defect was found and lane
surfaces (`maistro/tasks`, `maistro/runs/admission`, server `main.py` wiring)
are byte-identical to the previously verified state (`git diff a994af1447..
8bf0263c` on those paths is empty). Battery re-executed by this reviewer with
`MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@127.0.0.1:21435/maistro`
(lane pg `auto-1114-pg2`, PG18, `alembic upgrade head` clean at this head):

- `test_admission.py` + `test_issue_1114_repro.py` = **60 passed, 0 skipped**;
  full `packages/maistro-core/tests/tasks/` = **341 passed, 0 skipped** — both
  PG crash boundaries and both stranded-claim terminal-disposition tests
  executed for real.
- Prior finding re-proven fixed by name at this head:
  `test_recovery_terminalizes_a_running_claim_whose_node_run_has_no_attempt`
  and `test_postgres_lone_node_run_is_not_stranded_claim_evidence` PASSED
  (terminalization keys on Attempt evidence via `_has_attempt_evidence`,
  queue.py:147/562 — a lone NodeRun is no longer treated as evidence).
- `packages/maistro-server/tests/api/test_main.py` = 17 passed (lifespan
  `queue.recover(run_store)` wiring intact).
- Gates re-run: `ruff check .` clean; core+server `check-suite-inventory` ok;
  mypy six-package set Success (713 files); `check-execution-lifecycles` OK
  19/19 (no second lifecycle); `check-ac-state` rc=0; `check-compliance` rc=0.
- `check-vulture-baseline.py` rc=1 at this head (~891 NEW identities, ~220
  "no longer found") — **develop-side drift inherited via the mandated sync**,
  not lane-authored: every implicated file (`hive-conductor/backend/**`,
  `maistro_server/api/*`, `maistro_server/main.py::unhandled_exception_
  handler`, bootstrap/canvas/orchestrator identities) is byte-identical to the
  develop base `55c5ad892` (`git diff 55c5ad892..8bf0263c` on those paths is
  empty), the ledger differs only by the lane's ensemble `recover` prune, and
  no lane surface or lane test appears in the NEW lists (lane tests remain
  properly ledgered). The gate therefore fails identically at the develop base
  itself; the previous round's rc=0 was against the older develop `2c8022fe8`.
  No repair action possible from this lane without touching out-of-scope
  surfaces; recorded for the develop-side owners.
- Closure-keyword audit repeated: 0 `fixes/closes/resolves` in branch commit
  subjects/bodies at this head; live `gh pr view 1488` body says only
  "Refs #1114", headRefOid matches `8bf0263c411b`.

All issue acceptance criteria re-proven at this head by the executed tests
above; no source changes made this round — this note is the only tree delta.

## Verification record (L1114 repair @ 7ef64ca72, third develop sync + radon repair)

Repair round for the prior CI finding ("Quality gate (Pillars 1-4, 7, 8) =
failure" at `101ad20cd`). Root cause found by re-running the gate's own steps
locally: **`scripts/check-radon-baseline.py` rc=1** — the lane's #1114 repair
commit `d08f85598` grew `TaskRunAdmitter.record_transition` to C(12), an
unbanked raise the trusted-base ratchet must refuse (self-authorization is
structurally impossible: grants are read from the base revision). The prior
rounds' gate lists omitted radon, which is why it surfaced only in CI.

Fix: behavior-preserving extraction of the two status-classification guards
from `record_transition` — `_is_phase_only_transition` (claiming-store
QUEUED/RUNNING phase advance) and module-level
`_must_resume_before_terminalizing` (WAITING park, #143). `record_transition`
leaves the C-or-worse set entirely; ratchet reports 68 -> 68 blocks, rc=0,
no grant and no ledger edit needed.

Battery executed at `7ef64ca72` (merge of develop `80ce0d998`, 12 commits,
conflict-free) with real PG (`MAISTRO_TEST_PG_DSN` on the lane container):

- `packages/maistro-core/tests/tasks/` = **363 passed, 0 skipped** (was 341;
  the sync added #325 purge-driven tests). PG crash boundaries re-proven by
  name: `test_postgres_death_after_run_admission_executes_original_identity`,
  `test_postgres_death_after_receipt_before_notification_executes_original_identity`,
  `test_postgres_death_between_dispatch_phase_and_claim_executes_original_identity`,
  `test_postgres_malformed_admission_gets_a_terminal_disposition`,
  `test_postgres_stranded_running_claim_gets_a_terminal_disposition`,
  `test_postgres_queued_task_rehydrates_after_queue_restart`.
- `packages/maistro-server/tests/api/test_main.py` = 17 passed (lifespan
  `queue.recover(run_store)` wiring intact).
- Every `quality-gate` (Pillars 1-4/7/8 job) step green: ruff check + format;
  radon ratchet (after fix); `bump_version --check` (35 sites); release
  consistency; doc links; enumerations; vendor IFEval + BFCL; xenon 0 <= 77;
  **vulture 1412 -> 1411 rc=0** (the develop-side drift recorded last round
  is resolved by develop commits arriving in this sync); reachability,
  credential authority, wiring reads, agent-store writes, contract markers,
  convergence matrix, reachability dispositions, security inventory, image
  inventory, backlog consistency, merge markers, durable tables; `alembic
  upgrade head` on a fresh database rc=0; acceptance-state ratchet rc=0 with
  PG (ledger unchanged); `mypy --strict packages/maistro-core/src` Success
  (633 files) and six-package mypy Success (717 files); pyright 20 <=
  baseline 21; Hypothesis `formal/` 663 passed; `check-execution-lifecycles`
  OK 19/19; model egress; fitness 7 passed; interrogate floors 50.5 / 56.3 /
  70.4 / 54.5 all above minimum.

No test additions this round; the inventory delta is unchanged.

## Verification record (L1114 independent verify @ 6d8a0fe4c, develop ca4caec merged)

Independent verification at the exact lane head `6d8a0fe4c4b5` (merge of develop
`ca4caec7d` into auto-1114; worktree clean, no source edits this round). Real PG:
`MAISTRO_TEST_PG_DSN` against the lane container (pg16, alembic at 042 = head).

Executed green at this head:

- `packages/maistro-core/tests/tasks/` = **363 passed, 0 skipped**; the 25
  acceptance-critical tests re-proven individually by name (-k run, all PASSED):
  both PG crash boundaries (`..._death_after_run_admission_...`,
  `..._death_after_receipt_before_notification_...`), the phase/claim boundary
  (`..._death_between_dispatch_phase_and_claim_...`),
  `..._malformed_admission_gets_a_terminal_disposition`,
  `..._stranded_running_claim_...`, `..._lone_node_run_...`,
  `test_a_run_with_no_living_receipt_is_recovered_from_durable_facts`,
  `test_recovered_dispatchability_is_anchored_on_the_canonical_run`,
  `test_recovered_task_runs_under_the_original_canonical_identity`,
  duplicate-fence trio, `test_first_dispatch_writes_running_together_with_its_evidence`.
  Crash tests verified non-hollow: real `_ProcessDeath` BaseException injection
  after the durable admit()/receipt commits against `ClaimingPgRunStore`, then
  original Run/NodeRun/Attempt identity asserted post-recovery.
- `packages/maistro-server/tests/api/test_main.py` = 17 passed (lifespan
  `queue.recover(run_store)` wiring intact at main.py:334).
- ruff check + format, radon ratchet 67->67 rc=0, vulture ledger rc=0,
  check-execution-lifecycles 19/19 OK, model-egress, fitness, xenon 0<=77,
  bump_version/release/doc-links/enumerations/vendor x2, reachability +
  dispositions + credential/wiring/agent-store/contract/convergence/security/
  image/backlog gates all rc=0; mypy --strict core OK and pyright 21<=21
  (after `uv sync --all-extras` + quality tools, matching CI env); interrogate
  4 floors OK.
- Closure-keyword audit: 0 `fixes/closes/resolves #N` in branch commit
  subjects/bodies; live PR 1488 body says only "Refs #1114"; headRefOid matches
  the reviewed head.

**RED reproduced — new blocking finding.** The CI job "Quality gate
(Pillars 1-4, 7, 8)" is FAILURE at this head (run 36229550253, job
108369977475), and `scripts/check-ac-state.py --run-tests --ratchet --mandate
ca4caec7d` reproduces rc=1 locally (PG wired):

1. `FAIL: the repository moved away from its recorded state` —
   `design_coverage: 37.6277 falls below the floor of 38.0924` (floor folded
   from 75 notes at the develop base). The lane's own note still records
   37.2884 from an older develop; the ratchet's remediation is restore the
   evidence or `--bank` the fall with justification in the diff.
2. `FAIL: authorized floor(s) independent landings have superseded` — the
   `ac-state` `design_coverage@33.9095` grant (authored for #729) in
   `quality/ratchet-authorizations.json` must be pruned: auto-1138/auto-1158/
   auto-48 now clear that floor independently.

Both failures are ledger reconciliation on lane-reachable surfaces
(`quality/ac-state-notes/auto-1114.json` is a lane surface); every other
quality-gate step passes locally at this head, so this is the blocking driver.
Not locally executed: `pytest formal/` (CI formal-conformance = SUCCESS
separately; 663 passed at 7ef64ca72), `alembic upgrade head` on a fresh DB
(container already at 042), and the still-IN_PROGRESS CI jobs (test,
integration-scope, Coverage gate, docker-build) — all UNVERIFIED.
