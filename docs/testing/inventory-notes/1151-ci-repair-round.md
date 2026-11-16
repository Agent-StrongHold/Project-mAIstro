# #1151 CI repair round

## Frozen scope

- Assigned issue: #1151 only; branch `auto-1151`.
- Starting HEAD: `c67eb1624b229606a60d6d06e89bf22a16624fc4`.
- Supplied develop base: `e708451b3887c8a1540d5b7a3eefe827ac0755df`.
- Worktree initially clean; no sync conflict or uncommitted salvage required.
- Evidence: supplied `dispatch-context.json`, prior result from job
  `b1e21fcd60f041fc841ba1ee9db07089`, current production recovery sources,
  adjacent #1151 tests, relevant accepted ADRs and exact vulture gate.
- Repair files: this report and, only for reproduced retained identities,
  `quality/vulture-baseline.json`. Any actual dead-code fix will be documented
  here before implementation. No new scheduler, authorization or recovery policy.
- No driver `check-*.log` files were supplied in this job directory.

## Ambiguity and assumption

The issue is a parent with explicit blocked design/rollout items, not authority
for a monolithic recovery rewrite. This round is the explicitly assigned
exact-debt-ledger CI repair plus focused acceptance revalidation. Prior findings
are hypotheses to check, not permission to bypass pending decisions or invent
lease/death evidence. Existing blocked parent acceptance remains visible.

## Progress

- Verified starting HEAD and clean tree.
- Read prior result: broad parent acceptance was BLOCKED; no prior test claim
  will be treated as new validation.

- Exact requested Vulture command passed (exit 0): 1321 findings / 1321
  reviewed identities, no unclassified/unbanked/stale identities. Analyzer 2.16;
  gate resolved base `e708451b3887`. No ledger amendment is justified.
- Read accepted ADR-b36a, ADR-08f0, ADR-6e2a. Pending decisions cannot be
  overridden by continuation status; absent lease evidence is not proof of death.
  These restrictions reconcile the issue's broad acceptance with its design holds.

- `uv sync --locked --extra dev`: passed (214 packages checked).
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3333 files).
- Core acceptance collection: 1003 nodes. Execution with real PostgreSQL 18.6,
  migration 063, using the existing isolated `auto-1151-pg` service: **999 passed,
  4 unchanged strict xfails, no skips** in 121.27s. Logs:
  `/tmp/1151-core-collection.log`, `/tmp/1151-core-acceptance.log`.
  Xfails remain characterization of immediate terminal settlement, empty-frontier
  eligibility, terminal-failure observation and claim-free checkpoint-1 behavior;
  they are not evidence that those expectations pass.

- Hive canonical cadence/delegation tests: **21 passed**, no skips (2.81s),
  `/tmp/1151-hive.log`.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  passed, 16649 nodes, no duplicate evidence; `/tmp/1151-inventory.log`.
- `uv run python scripts/check-doc-links.py`: passed, 2433 Markdown files,
  no broken links; `/tmp/1151-doc-links.log`.
- `git diff --check`: passed.
- Executed the already-collected PostgreSQL inspection node separately with
  `-x -q -s`: **1 passed**, `/tmp/1151-pg-inspection.log`. With `limit=1`,
  ten unchanged prefix Runs, three NodeRuns and four Attempts per prefix node,
  peer-first repair inspected 11 candidate Runs and 121 Attempt rows. Repeated
  and fresh-Container zero-repair ticks each reread 10 Runs and 120 Attempt rows.
  These are returned RunStore rows, not query-planner/database page costs.

## Exact focused test commands

Executed with `MAISTRO_TEST_PG_DSN` supplied from the existing isolated lane
service configuration (credentials omitted). The PG fixture truncates scratch
records; no shared development/production database was used. PostgreSQL version
and Alembic revision were independently queried before testing. No new migration,
process, scheduler, gate configuration or source patch was needed.

```sh
uv run pytest packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/runs/test_pg_spine_crash_windows.py packages/maistro-core/tests/runs/test_chat_attempt_recovery.py packages/maistro-core/tests/runs/test_chat_execution.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/runs/test_crash_window_invariants.py packages/maistro-core/tests/runs/test_recovery_completion_budget.py packages/maistro-core/tests/runs/test_run_terminal_recovery_acceptance.py packages/maistro-core/tests/runs/test_recovery_inspection_budget.py packages/maistro-core/tests/runs/test_sqlite_recovery_index.py -x -q -ra
uv run pytest packages/hive-conductor/backend/tests/test_canonical_recovery_cadence.py packages/hive-conductor/backend/tests/test_dag_recovery.py -x -q -ra
uv run pytest 'packages/maistro-core/tests/runs/test_recovery_inspection_budget.py::test_recovery_inspection_measurements[postgres-peer-first-3-4-10]' -x -q -s
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
```

The first command was also run with `--collect-only -q` before execution. It
includes 16 real-PG spine crash-window nodes, 15 parked-disposition nodes across
three stores, and 96 inspection measurements across three stores. These counts
were read from this round's collection, not copied from earlier reports. Other
logs: `/tmp/1151-vulture-before.log`, `/tmp/1151-sync.log`, `/tmp/1151-ruff.log`,
`/tmp/1151-format.log`.

## Reachable behavior and acceptance ledger

`Container.recover_abandoned_attempts` invokes canonical reclaim and terminal
Attempt replay (`container.py:1253-1254`); Hive's real cadence delegates to it
(`services/canonical_recovery.py:38-47`). Graph due/queued recovery calls the
existing persistence-reconciler seam (`graph/durable_runs/recovery.py:172-176`).
Tests exercise these shipped seams, not a replacement repair implementation.
The PG crash suite uses actual PgRunStore and PgGraphContinuationStore on
independent pools; its in-process injected exceptions are not OS-process kills
or network-level uncertain-COMMIT proofs.

| Retained criterion | Executed evidence and limits |
| --- | --- |
| One canonical bounded/indexed RUNNING sweep re-derives persisted facts | PG backlog test, SQLite index-plan test and canonical recovery suites pass. Graph candidate paging is bounded; total Container inspection bound is **UNSATISFIED**, not established by its repair quota. |
| Required terminal NodeRuns settle without a new Attempt | PG `test_run_settlement_lost_after_the_last_node_run_commits` and `test_an_attempt_completion_committed_before_reconciliation_settles` pass through the public Container tick. Immediate Graph-only settlement remains a strict xfail, not this proof. |
| Lost frontier / `resume_at=None` cannot strand eligible work | PG `test_a_frontier_node_run_without_its_checkpoint_is_made_due_and_resumed` and Graph recovery contracts pass. Exhaustive checkpoint/death coverage remains **UNVERIFIED**. |
| Terminal-continuation disagreement, including WAITING/PAUSED | Terminal canonical projection and RUNNING/terminal repair proofs pass. All four parked pairs preserve the pending timer/HITL decision and allow an unrelated repair. Their terminal mismatches are injected, not proven walker-reachable. Authorized parked repair is **UNSATISFIED / DESIGN_BLOCKED**: `canonical_store.py:640` admits only RUNNING here; ADR-08f0 forbids bypassing the decision. |
| QUEUED-continuation / RUNNING-Run checkpoint-1 | Real-PG elapsed-claim resume and live-claim refusal pass. Claim-free behavior remains a strict xfail; universal checkpoint-1 coverage **UNVERIFIED**. |
| Persistence failure after success retains result/policy/recoverability | PG committed-success acknowledgement loss, rejected-write parking, and PURE/NON_RETRYABLE replay pass. Uncommitted output is not fabricated as success. Universal output preservation and every retry-budget case **UNVERIFIED**. `runs/execution.py:751-767` still makes one terminal write; adding an inline retry would contradict the tested chat recording contract. |
| Chat lease/fence/reclaim and non-swallowed terminal-write failure | 13 chat-recovery, 55 chat-execution and 14 fencing tests pass, plus both real-PG chat rejected-write/lost-ack cases. ChatDispatchUnrecorded carries the original response/cause; the provider is called once. Complete real-PG worker-death/terminal-write matrix **UNVERIFIED**. |
| Replica idempotence and fencing | PG concurrent-replica settlement, fixed-point assertions and execution-fencing suite pass. PG resume rotates ordinal/fence without rewriting the old Attempt. |
| Every crash window plus chat on PostgreSQL | All 16 existing real-PG spine cases pass with no skips. They do not establish complete process-death, network-COMMIT or forced-interleaving coverage; complete criterion **UNVERIFIED**. |
| Sweep bounded/indexed rather than unbounded history scan | Canonical RUNNING selection excludes terminal Run history and uses paging. `container.py:1372-1390` bounds repairs, resets its local cursor and hydrates nested histories; measured 11 Runs/121 Attempt rows at limit=1. A total inspection bound remains **UNSATISFIED**, with policy held under #1098. |
| #804 consumes settled canonical truth, no private compensator | All 21 Hive cadence/delegation tests pass and production cadence calls Container recovery. Full #804/server activation acceptance remains **UNVERIFIED**. |

## Disposition and checkpoint

**BLOCKED for parent acceptance.** The requested CI failure does not reproduce;
no dead identity was found and no ledger change is warranted. The retained parent
holds are behavior/design and proof gaps, not a reason to weaken gates, bypass
pending decisions, retry terminal writes blindly, or invent a competing recovery
authority. No GitHub changes, fetch/merge or activation were performed.

This round changes only this evidence/handoff note. No tests were added or
removed, so no `inventory-delta` is required. Existing tests and unmodified
inventory deltas remain authoritative. Local commit is reported in the worker
response. Progress: checked 1 issue, done 1 scoped CI investigation/revalidation,
skipped 0 issues, errors 0 validation failures. Next: owner disposition of parked
conflicts/inspection policy and the remaining durability/activation proofs; do
not redispatch an unspecified ledger repair when the exact gate passes.
