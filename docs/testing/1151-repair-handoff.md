# Issue #1151 repair checkpoint

## Frozen scope

- Assigned issue: #1151 only; branch `auto-1151`.
- Starting HEAD: `bfb09d087926c85c538232feb0baf98ff7bc53fa` (verified); supplied develop base: `5f714e1beed5efbc589234acb78bdf96f811b651`.
- Starting worktree clean; no incoming changes to salvage.
- Evidence snapshot: `/home/dev/maistro/jobs/482f5ede23e94f38b8fc2689d78eeeaf/dispatch-context.json`; prior result `32a74e345ede42f1ba8da23918f85adc/result.json`.
- No `check-*.log` files present in supplied job directory at start.
- File scope: current #1151 reconciliation implementation and adjacent tests/inventory notes, relevant ADRs and CI scripts (inspection), `quality/vulture-baseline.json` only if the expressly authorized exact-ledger repair needs it.
- No GitHub mutations, no develop sync unless evidence establishes a sync conflict.

## Initial evidence

Prior result reports missing total inspection bound, intentionally preserved parked/terminal disagreement under ADR-08f0, and incomplete crash-matrix proof. Treat these as hypotheses to verify, not established current failures. Writer assignment takes precedence over the generic verifier no-edit paragraph.

## Progress

- Read complete snapshotted issue body and latest eight comments. Its explicit design holds still prohibit a new scan-work policy or parked-conflict disposition. Broad acceptance cannot override those holds or accepted ADRs.
- `uv sync --locked --extra dev`: exit 0 (`/tmp/1151-482f-sync.log`).
- Exact requested vulture command: exit 0 (`/tmp/1151-482f-vulture.log`). No actual unbanked identity evidence; no ledger change justified.
- No conflict markers or uncommitted incoming work: previous block was acceptance/design, not a develop-sync conflict. No fetch/merge needed.
- Read accepted ADR-b36a, ADR-08f0 and ADR-6e2a, production Container and Graph recovery, and adjacent PG crash/inspection tests. Canonical RUNNING selection is indexed/paged, but Container's repair quota does not cap nested inspection. Parked/terminal disagreement remains deliberately refused without a pending decision.
- `uv run ruff check .` and `uv run ruff format --check .`: exit 0 (logs `/tmp/1151-482f-{ruff,format}.log`).
- Existing lane-specific `auto-1151-pg` PostgreSQL 18 service discovered on localhost:18551; will validate its scratch database before running destructive test fixtures. No other lane's database will be used.
- Verified lane scratch PostgreSQL 18.6, migration 063. Focused collection and execution with actual PgRunStore/PgGraphContinuationStore: **999 passed, 4 pre-existing xfails, zero skips** (88.25s); logs `/tmp/1151-482f-{collection,core}.log`. Four xfails describe immediate Graph settlement, empty-frontier claim, terminal-failure observation and claim-free checkpoint-1 expectations. They are not passing acceptance evidence.
- Hive cadence/delegation tests, core suite-inventory gate, doc-links gate and `git diff --check`: exit 0; logs `/tmp/1151-482f-{hive,inventory,doc-links}.log`.
- Re-executed already-collected PG inspection node `[postgres-peer-first-3-4-10]` with `-s`: exit 0; `/tmp/1151-482f-inspection.log` records inspected rows independently of repair counts.
- No runtime/test/ledger change is justified by these results. Hive: **21 passed**; core inventory: **16673 nodes**, zero duplicate evidence; doc links: **2443 files**, zero broken relative links.

## Commands and acceptance evidence

Commands executed from the assigned worktree, with long timeouts. PG credentials were loaded from the existing lane scratch service into the subprocess environment and are intentionally omitted. Fixtures truncate scratch tables; no other database was touched.

```sh
uv sync --locked --extra dev
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run ruff check .
uv run ruff format --check .
uv run pytest packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/runs/test_pg_spine_crash_windows.py packages/maistro-core/tests/runs/test_chat_attempt_recovery.py packages/maistro-core/tests/runs/test_chat_execution.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/runs/test_crash_window_invariants.py packages/maistro-core/tests/runs/test_recovery_completion_budget.py packages/maistro-core/tests/runs/test_run_terminal_recovery_acceptance.py packages/maistro-core/tests/runs/test_recovery_inspection_budget.py packages/maistro-core/tests/runs/test_sqlite_recovery_index.py -x -q -ra
uv run pytest packages/hive-conductor/backend/tests/test_canonical_recovery_cadence.py packages/hive-conductor/backend/tests/test_dag_recovery.py -x -q -ra
uv run pytest 'packages/maistro-core/tests/runs/test_recovery_inspection_budget.py::test_recovery_inspection_measurements[postgres-peer-first-3-4-10]' -x -q -s
uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests
uv run python scripts/check-doc-links.py
git diff --check
```

The core command also ran with `--collect-only -q` instead of execution flags. Its exact node IDs are in `/tmp/1151-482f-collection.log`.

| Retained issue criterion | Current-head executed evidence and limits |
| --- | --- |
| One canonical bounded/indexed RUNNING reconciliation sweep | PG backlog paging, SQLite index plan and recovery suites pass. Production `canonical_store.py:442` caps Graph candidates; `container.py:1371` caps repairs only. Total inspection bound **UNSATISFIED**. |
| Terminal required NodeRuns settle without a new Attempt | PG `test_run_settlement_lost_after_the_last_node_run_commits` and `test_an_attempt_completion_committed_before_reconciliation_settles` pass through public Container recovery without redispatch. Immediate Graph-only settlement remains an xfail, not this evidence. |
| Lost frontier / missing resume deadline cannot strand work | PG `test_a_frontier_node_run_without_its_checkpoint_is_made_due_and_resumed` and named crash oracle pass. Exhaustive crash-boundary coverage **UNVERIFIED**. |
| Terminal continuation disagreement, including WAITING/PAUSED | Terminal canonical projection and RUNNING/terminal tests pass. Four parked pairs preserve pending decisions and unrelated repair isolation across memory/SQLite/PG. Their contradictory terminal projections are injected, not proven walker-reachable. `canonical_store.py:639` excludes parked canonical states; authorized repair **DESIGN_BLOCKED** by the issue hold and ADR-08f0. |
| QUEUED-continuation / RUNNING-Run checkpoint-1 | PG expired-claim recovery and live-claim refusal pass. Claim-free expectation remains xfailed; universal criterion **UNVERIFIED**. |
| Persistence failure after successful execution retains result/retry safety/recoverability | PG committed-success lost acknowledgement, rejected success-write ownership/parking and PURE/NON_RETRYABLE replay tests pass. `runs/execution.py:751-767` still performs one terminal write, not the historical claimed inline retry. Uncommitted output is not fabricated. Universal durable output preservation/retry-budget coverage **UNVERIFIED**. |
| Chat canonical lease/fence/reclaim and non-swallowed terminal-write failures | Chat recovery/execution/fencing tests and both PG completion-write cases pass. Production `chat_execution.py:108` defines response-carrying ChatDispatchUnrecorded; `:212` defaults to finite leased execution. Full real worker-death matrix **UNVERIFIED**. |
| Replica idempotence and fencing | PG concurrent sweep convergence, repeated fixed points, live ownership refusal and fence rotation tests pass. No competing execution authority added. |
| PostgreSQL crash-injection/interleaving coverage for every verified window plus chat | Existing PG spine crash suite passes without skips using independent pools and both real durable stores. These are injected in-process failures, not OS process death or network-level uncertain-COMMIT coverage. Complete matrix **UNVERIFIED**. |
| Sweep bounded/indexed, not an unbounded historical scan | Terminal Run history is excluded. PG measurement at `limit=1` reads **11 candidate Runs, 122 listed NodeRun rows, 121 listed Attempt rows** for one repair; repeated/fresh-Container zero-repair ticks reread **10/120/120**. Getter reads are additional. Counts are returned API rows, not database planner costs. Total-work bound **UNSATISFIED**; policy remains held under #1098. |
| #804 consumes canonical truth, no Workspace-private compensator | **21 Hive tests pass**; `services/canonical_recovery.py:40` calls Container recovery. Full #804/server activation acceptance **UNVERIFIED**, not inferred from unit cadence tests. |

## Final disposition

**BLOCKED for parent acceptance.** Requested CI failure does not reproduce: vulture 2.16 reports 1321 reviewed identities and 1321 findings against supplied base `5f714e1beed5`. Editing a passing ledger would be cosmetic, not a repair. Missing scan policy and parked-disposition authority cannot be resolved by violating the explicit issue holds or accepted ADRs. No guessed terminal retry, pending-decision override, new scheduler, activation, or GitHub mutation was made.

Only this handoff file changes. No tests added/removed, so no inventory delta is required. All validation commands above exited 0; xfails are explicitly not acceptance passes. No source repair or regression fix is claimed. Existing work is preserved.

Checkpoint: checked 1 issue; done 1 scoped CI investigation and acceptance revalidation; skipped 0 issues; errors 0 command failures. Next: owner-reviewed parked disposition and scan policy, then missing durability/activation proofs. Do not redispatch the same unspecified ledger repair while its exact gate passes. This report will be locally committed before handoff.
