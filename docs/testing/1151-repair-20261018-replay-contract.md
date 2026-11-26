# #1151 repair: PostgreSQL replay policy after a lost success write

## Scope and disposition

Assigned branch/worktree: `auto-1151`; starting head
`be7bd83be5ec024ebf7657943df20079a4859b36`, clean. Supplied develop base:
`eec7a587039e632500942dd390f82d743863f5e3`. No merge conflict existed; no sync,
GitHub mutation, ledger edit, gate change or production activation was performed.
The starting branch already diverges from the supplied base; unrelated inherited
differences were not modified. This round changes only the PG test, its inventory
note and this report.

Read repository instructions, the captured issue body and prior result, accepted
ADR-b36a, ADR-08f0 and ADR-6e2a, production recovery/execution paths and adjacent
tests. The issue explicitly reserves parked-conflict repair and scan policy for
design review. ADR-08f0 requires preserving pending decisions; arbitrary terminal
continuation status cannot authorize their override. Those holds remain real,
not CI failures to bypass. The exact Vulture scan passes without unbanked debt,
so the requested evidence-based ledger repair requires **no amendment**.

## New evidence

`packages/maistro-core/tests/runs/test_pg_spine_crash_windows.py` extends the
existing lost-success-write test with PURE/NON_RETRYABLE parameterization (+1
collected test). Both canonical authorities are actual PostgreSQL stores. After
one successful node execution and a pre-commit completion-write failure:

- Independent recovery reads verify RUNNING ownership and no persisted result.
- The live tick changes nothing; expiry reclaims and parks without fabricated
  output. Repeated recovery leaves full canonical history unchanged.
- Explicit resume uses a third fresh pool and the persisted claim/lease expiry,
  not sleeps or extra ticks. A fresh ordinal, Attempt ID and fence are required.
- PURE executes again and accepts the new committed output. NON_RETRYABLE records
  `ReplayRefused` without executing the node body again. Run, NodeRun and
  continuation agree; the original cancelled Attempt stays unchanged.

No production change was justified by this proof: the existing replay-contract
path passes. The first test draft omitted the tick clock on explicit resume and
correctly received `LiveAttemptOwned`; supplying the persisted claim expiry fixes
that fixture, not production. A process-local mutation making the production
`_node_replay_semantics` seam always return PURE makes the NON_RETRYABLE case fail
(COMPLETED instead of FAILED). No source file was mutated for that check.
This tests policy consumption, not all retry budgets or preservation of output
that never committed. Pool isolation is not an OS-process kill/network partition.

## Executed validation

Logs are under `/home/dev/maistro/jobs/05301dde7e604a07a5d513c2af04fe13/`.
No driver `check-*.log` files existed at entry. These logs were produced locally;
connection credentials were only passed through subprocess environment using the
existing isolated `auto-1151-pg` service.

- Starting PG crash-window suite: **13 passed** (`check-pg-baseline.log`).
- Extended PG suite: **14 passed**, no skips (`check-replay-contract-after-clock.log`).
  Exact collected IDs: `check-pg-collection.log`.
- Mutation sensitivity: **1 expected failure / 13 deselected**
  (`check-replay-mutation.log`).
- Broad core command below: **997 passed, 4 unchanged strict xfails, no skips**
  (`check-core-acceptance.log`). Strict xfails are not acceptance proof.
- Hive canonical cadence/delegation: **21 passed**, no skips (`check-hive.log`).
- `uv run ruff check .`: passed. Initial targeted lint found import ordering;
  corrected before final whole-tree check (`check-ruff.log`).
- `uv run ruff format --check .`: passed, 3312 files (`check-format.log`).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  passed, 1322 findings / reviewed identities (`check-vulture.log`).
- `uv run python scripts/check-radon-baseline.py`: passed, 137 reviewed blocks
  (`check-radon.log`).
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  passed, 16585 collected nodes (`check-inventory.log`).
- `uv run python scripts/check-test-duplicates.py`: passed (`check-duplicates.log`).
- `git diff --check`: passed.

```sh
uv run pytest packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/runs/test_pg_spine_crash_windows.py packages/maistro-core/tests/runs/test_chat_attempt_recovery.py packages/maistro-core/tests/runs/test_chat_execution.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/runs/test_crash_window_invariants.py packages/maistro-core/tests/runs/test_recovery_completion_budget.py packages/maistro-core/tests/runs/test_run_terminal_recovery_acceptance.py packages/maistro-core/tests/runs/test_recovery_inspection_budget.py packages/maistro-core/tests/runs/test_sqlite_recovery_index.py -x -q -ra
uv run pytest packages/hive-conductor/backend/tests/test_canonical_recovery_cadence.py packages/hive-conductor/backend/tests/test_dag_recovery.py -x -q -ra
```

## Acceptance ledger for this exact tree

| Retained criterion | Executed evidence / remaining limitation |
| --- | --- |
| Indexed/bounded RUNNING candidates and re-derivation | PG backlog and SQLite index proofs pass; total inspected-work bound **UNVERIFIED**. |
| Required terminal NodeRuns settle without a new Attempt | PG last-NodeRun/committed-Attempt crash proofs and canonical tick suites pass. |
| Lost frontier / resume_at=None | PG frontier crash and recovery contract suites pass with existing quiet-period/ownership guards. |
| Canonical/terminal-continuation disagreement including parked Runs | Terminal canonical projection tests pass. Four parked pairs preserve decisions; general conflict repair **UNSATISFIED / DESIGN_BLOCKED**, `canonical_store.py:640`. |
| Checkpoint-1 QUEUED continuation / RUNNING Run | PG expired-claim recovery and live-claim refusal pass. |
| Success-write failure preserves result, retry policy and recoverability | Committed acknowledgement-loss proof passes; new pre-commit proof confirms canonical parking and PURE/NON_RETRYABLE replay. Universal uncommitted-output preservation / every retry-budget case **UNVERIFIED**. |
| Chat canonical lease/fence/reclaim and non-swallowed terminal failure | Chat recovery, fencing and chat execution suites pass, including no-inline-retry recording contract. Complete real-PG #1170 terminal-write matrix **UNVERIFIED**. |
| Replica idempotence/fencing | Independent-pool settlement and fencing suites pass; new resume retains old history and rotates fence. |
| Every crash/terminal-write window on PostgreSQL | 14 PG crash cases pass; universal process-death/network-COMMIT/interleaving coverage **UNVERIFIED**. |
| Bounded/indexed sweep rather than historical scan | Indexed candidate checks pass; inspection matrix confirms unchanged prefixes/nested histories still cost work. `container.py:1372` bounds repairs, not inspected work: **UNSATISFIED**, policy held under #1098. |
| #804 consumes canonical truth | 21 Hive delegation/cadence tests pass; full #804 acceptance **UNVERIFIED**. |

Parent verdict: **BLOCKED**, not integration-ready. No new repair policy can be
inferred from passing characterization tests. Checkpoint: checked 1 assigned
issue, done 1 scoped proof extension, skipped 0 issues, errors 0 remaining focused
validation failures. Next: design-owner disposition for parked conflicts and scan
work, plus outstanding durability matrix. Local commit identity is supplied in
the worker response; no issue closure is authorized.
