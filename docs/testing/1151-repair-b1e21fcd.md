# #1151 repair — b1e21fcd

## Frozen scope

- One assigned item: #1151; branch `auto-1151`, starting HEAD
  `81237a589552c2453d36d1860aed3f2e52646170`.
- Supplied develop base: `d8675ac8933c21db141db0bc42584404474b44b3`.
- Worktree initially clean; existing commits are preserved.
- Evidence sources frozen: supplied dispatch-context.json, prior result
  `956dad7e95fb4c2faf41bf5711d84e55/result.json`, current repository.
- Candidate edit surfaces: canonical durable reconciliation, terminal execution
  persistence, their existing core tests and inventory notes, this report, and
  `quality/vulture-baseline.json` only for explicitly requested CI repair.
- No check-*.log files supplied in the job directory. Run checks locally.
- Prior report says BLOCKED: parked/terminal disagreement, missing terminal-write
  retry, total-work bound, incomplete acceptance evidence. Revalidate rather than
  accepting those assertions.
- Existing branch differs from supplied base in unrelated surfaces; do not edit
  those surfaces or discard prior work. No develop-sync conflict is currently
  present, so the conditional merge instruction does not apply.

## Progress

- Read the supplied issue body and accepted ADR-b36a/08f0/6e2a. The issue
  explicitly holds parked-conflict repair and scan policy behind design review;
  ADR-08f0 forbids overriding a parked pending decision. Reconciliation of the
  broad acceptance wording must preserve that table, not invert the tests.
- Executed the exact requested vulture gate: PASS, 1322 findings / 1322 reviewed
  identities, zero unclassified. No identity requires ledger amendment. The gate
  reports its comparison base as `35a72ff54d4f`, not the supplied develop tip.
- No evidence-backed vulture repair is available. Do not invent dead code or
  edit an already matching ledger merely to produce a diff.
- Source confirms `canonical_store.py:640` restricts terminal Graph repair to
  canonical RUNNING; parked tests inject the terminal projection rather than
  proving a reachable production crash. They preserve pending decisions, not
  repair this disagreement.
- Source confirms `container.py:1372` bounds repairs, not inspected work, with
  nested full NodeRun/Attempt reads at :1336/:1304. Existing measurement tests
  explicitly assert growing reads and repeated scans.
- `runs/execution.py:751` performs one terminal write;
  `attempt_executor.py:862` only resolves committed acknowledgement loss.
  No universal preservation of uncommitted Graph output is claimed.
- Supplied develop base is not an ancestor of HEAD (ancestor command exit 1).
  This is assigned-head validation, not integrated-develop validation.
- Existing isolated PostgreSQL service `auto-1151-pg` is running and selected
  for validation. No other lane's database will be used.
- Core recovery/Graph/chat/fencing validation with actual PostgreSQL: **999
  passed, 4 existing strict xfails, no skips** (97.53 s). Xfails are immediate
  terminal-node settlement, empty-frontier eligibility, terminal projection
  settlement and claim-free checkpoint-1. They are not acceptance proof.
- Hive canonical cadence/DAG recovery: **21 passed** (2.09 s).
- Root Ruff check and format check pass (3330 files). Radon passes (137/137),
  core suite inventory passes (16609 nodes), duplicate check passes (1617 files,
  zero duplicate groups). Logs are in this round's job directory.
- No new tests or implementation changes are justified by the scanner results;
  no test inventory delta or ledger amendment is required.
- Additional measurement run: **96 passed** (71.39 s), no skips. Collected
  exact IDs for PG crash, parked-conflict and measurement files: **127 nodes**.
  At `limit=1`, PostgreSQL with 10 unchanged prefix Runs (3 NodeRuns and 4
  Attempts per node) reads 11 candidate Runs, 122 NodeRun rows and 121 Attempt
  rows to make one repair. Repeat and fresh-Container ticks each read 10
  candidate Runs, 120 NodeRun rows and 120 Attempt rows for **zero repairs**.
  These are RunStore API row counts (including repeated reads), not SQL query
  plans or database-internal work. This demonstrates why a repair limit cannot
  be cited as an inspected-work bound.

## Disposition and reconciliation

**BLOCKED.** No scanner defect exists to repair; broader acceptance still requires
reviewed parked-disposition/scan-policy decisions and missing integration proofs.
The previous block is not a develop-sync conflict. There is no unmerged state to
resolve. Existing source and test assertions are preserved; no silent retry,
forced terminalization of pending decisions, new scheduler, new execution owner,
or ledger/gate weakening was introduced. Only this evidence report changed.

The stale PR #2153 retry claim is not supported by this source. The existing
inventory note already discloses its removal and the chat contract. The current
PG tests explicitly assert one completion write and surfaced
`ChatDispatchUnrecorded`, so reintroducing an inline retry solely to match an old
PR summary would contradict actual tests. No GitHub edit is authorized.

## Commands and outcomes

Logs: `/home/dev/maistro/jobs/b1e21fcd60f041fc841ba1ee9db07089/check-*-worker.log`.
The PG connection was derived privately from the existing isolated service and
passed as `MAISTRO_TEST_PG_DSN`; no credential is recorded here. PG cases use
PgRunStore and PgGraphContinuationStore with independent pools. Exceptions at
API commit seams are not OS process kills or network-level COMMIT ambiguity.

```sh
uv run pytest packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/runs/test_pg_spine_crash_windows.py packages/maistro-core/tests/runs/test_chat_attempt_recovery.py packages/maistro-core/tests/runs/test_chat_execution.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/runs/test_crash_window_invariants.py packages/maistro-core/tests/runs/test_recovery_completion_budget.py packages/maistro-core/tests/runs/test_run_terminal_recovery_acceptance.py packages/maistro-core/tests/runs/test_recovery_inspection_budget.py packages/maistro-core/tests/runs/test_sqlite_recovery_index.py -x -q -ra
uv run pytest packages/hive-conductor/backend/tests/test_canonical_recovery_cadence.py packages/hive-conductor/backend/tests/test_dag_recovery.py -x -q -ra
uv run pytest packages/maistro-core/tests/runs/test_pg_spine_crash_windows.py packages/maistro-core/tests/graph/durable_runs/test_parked_terminal_continuation_disposition.py packages/maistro-core/tests/runs/test_recovery_inspection_budget.py --collect-only -q
uv run pytest packages/maistro-core/tests/runs/test_recovery_inspection_budget.py -x -q -s
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run python scripts/check-radon-baseline.py
uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests
uv run python scripts/check-test-duplicates.py
```

All commands above exited 0. Counts are recorded under Progress. Full-tree pytest
was not run. No implementation change means no fail-before/pass-after claim.

## Acceptance, checked against executed evidence

Here `PG` means `packages/maistro-core/tests/runs/test_pg_spine_crash_windows.py`.
All named tests below ran in the core command, without PG skips.

| Retained criterion | Evidence and remaining limit |
| --- | --- |
| Bounded/indexed canonical RUNNING enumeration and re-derivation | PG `test_the_running_sweep_pages_past_a_backlog_within_bounded_calls` and SQLite recovery index test pass. The PG backlog case can also reach residue through terminal continuation buckets; it is not an isolated index/query-plan proof. Total inspected-work bound **UNVERIFIED**, contradicted for the Container by measured growth. |
| Required terminal NodeRuns settle without another Attempt | PG `test_an_attempt_completion_committed_before_reconciliation_settles` and `test_run_settlement_lost_after_the_last_node_run_commits` pass through the public Container tick; persisted result/history and second-tick zero are asserted. |
| Lost frontier / resume_at=None cannot strand indefinitely | PG `test_a_frontier_node_run_without_its_checkpoint_is_made_due_and_resumed` and live-walker guard suites pass. Complete crash-position coverage **UNVERIFIED**. |
| Terminal continuation disagreement including WAITING/PAUSED | Terminal canonical projection and RUNNING-to-terminal repairs pass. Four parked cases preserve pending decisions and isolate a second repairable Run; they inject the mismatch. Reachability and an authorized parked-conflict repair remain **UNVERIFIED/UNSATISFIED**. |
| QUEUED continuation / RUNNING checkpoint-1 | PG elapsed-claim recovery and live-claim refusal pass. Claim-free case remains an existing strict xfail, not completion evidence. |
| Persistence failure after runtime success | PG rejected-write and lost-ack tests pass, including PURE/NON_RETRYABLE replay contracts and no contradictory terminal Run over a live Attempt. Uncommitted output remains absent in canonical storage; universal result preservation/node-policy coverage **UNVERIFIED**. No inline write retry exists. |
| Chat lease/fence/reclaim and surfaced recording failure; no no-lease sweep inference | Chat execution, recovery and fencing suites plus both PG `test_chat_completion_write_failure_recovers_from_committed_truth` cases pass. Full during-dispatch process-death/HTTP matrix **UNVERIFIED**. |
| Idempotence and replica fencing | PG `test_two_replicas_sweeping_concurrently_converge_on_one_settlement`, second-tick fixed-point assertions and execution-fencing suite pass. |
| PG crash/forced-interleaving proof for every window including chat | Existing API-seam PG cases pass with independent pools. Exhaustive process-death, transaction acknowledgement and continuation crash matrix **UNVERIFIED**; do not count memory/SQLite as PG durability. |
| Bounded/indexed sweep, not unbounded historical scan | Completed Run history is excluded in measurement tests; unchanged RUNNING Runs and nested history are reread. Repair quota is respected, but total inspected-work bound is **UNSATISFIED**. |
| #804 consumes canonical truth, no Workspace-private compensator | 21 Hive cadence/DAG tests pass using canonical seams. The cadence fixture is SQLite with an engine binding; complete #804/server integration remains **UNVERIFIED**. Source search under maistro-server finds the recovery name only in a chat docstring, not a direct tick caller. |

## Handoff

Checked: 1 issue. Done: assigned-head validation and committed evidence report.
Skipped: 0 issues. Failed validation commands: 0 (the separate ancestry probe
returns 1). Implementation/acceptance errors remain as recorded above. Next:
existing parked-disposition and scan-policy owners must resolve their retained
holds; integrated server/continuation/process-death proof must follow before
parent acceptance. No merge, activation, push or issue closure is authorized.

