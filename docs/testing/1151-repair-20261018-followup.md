# Issue #1151 follow-up repair

## Frozen scope and initial checkpoint

- Assigned worktree `/home/dev/Git/wt/auto-1151`, branch `auto-1151`.
- Starting head verified: `75fda88adbc4eb42e2fa34bd6fb915743435202e`; clean worktree.
- Process only issue #1151, supplied dispatch-context.json and prior result, and directly related canonical run/continuation recovery implementation, tests, inventory notes, ADRs, and exact-debt vulture gate. No GitHub mutations or refresh of dispatch lists.
- No `check-*.log` files were supplied in the job directory at initial inspection.
- Prior result is BLOCKED: parked/terminal disagreement, universal runtime-result preservation, bounded nested work, and complete acceptance require verification. Prior validation claims are not assumed true.
- Assumption: this is the writer repair lane. Accepted ADRs govern any conflicting issue requests; unresolved architecture conflicts will be recorded rather than bypassed.

## Results

Dispatch body inspected: general parked-conflict repair and rollout remain explicitly design-blocked. The permitted parent-held inspection measurement has no existing `test_recovery_inspection_budget.py`. Selected bounded work: measure the production Container terminal-replay scan with 0/1/2/10 unchanged pages, later repairable residue, nested rows, restart/repeat/peer-first cases. This is proof/measurement only, not a new fairness policy or an arbitrary scan threshold. Inspect adjacent architecture/tests before implementation; do not introduce a retry or pending-decision override. Starting branch contains unrelated inherited sandbox diffs versus supplied base; preserve them, do not modify them.

Read accepted ADRs b36a, 08f0 and 6e2a completely and inspected Container terminal replay, canonical continuation reconciliation, execution success persistence, and adjacent completion-budget/PG tests. Parked COMPLETED/FAILED disagreement still has no authorized general disposition. `_settle_provider_success` still invokes its terminal writer once; no universal output-preservation claim is justified.

Executed `uv sync --locked --extra dev`: passed. Exact requested Vulture gate: passed, 1322 reviewed identities / 1322 findings; no ledger amendment justified. Existing assigned `auto-1151-pg` is running on port 18551.

Measurement design: instrument actual store list/get methods around the public Container tick, counting returned Run/NodeRun/Attempt records (not physical SQL rows examined), including nested reconciliation reads. Matrix: 0/1/2/10 one-Run unchanged pages; 1 vs 3 NodeRuns, 1 vs 4 Attempts per NodeRun; normal and peer-first repair. Repeat and fresh-Container ticks must preserve all history and restart enumeration from the beginning. Memory/SQLite/PG fixture legs share this observation contract; fresh Container is not a database/process restart proof.

## Measurement checkpoint

- Added `test_recovery_inspection_budget.py` and inventory note (+96 collected nodes).
- Initial memory run: 3 passed then fixture admission refused its ninth root Run (default per-principal ceiling 8); corrected only the module's existing concurrency-limit fixture override to 32. Initial Ruff SIM102 corrected by combining conditions. No production/gate policy changed.
- Live PostgreSQL-enabled full new file: **96 passed, no skips**, 38.14s (`repair-inspection.log` in the assigned job directory).
- Concrete PostgreSQL observation at 10 unchanged pages, width=3/depth=4: first tick returns 1 repair after 11 candidate Runs, 122 list-returned NodeRuns and 121 list-returned Attempts. Repeated and fresh-Container ticks each return 0 repairs yet reread 10 candidate Runs, 120 list-returned NodeRuns and 120 list-returned Attempts; point reads are recorded separately. This refutes any interpretation of `limit=1` as a total inspected-record bound. It does not prove a full historical Run scan: the seeded terminal historical Run is excluded from the candidate API.
- All prefix/full-history fixed-point assertions passed; peer-first progress is observed exactly once. Negative control and broader validation completed below.

## Validation checkpoint

All logs named below are under `/home/dev/maistro/jobs/d13acb1b4a2f49d380b9e892e095603f`.

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3312 files.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: passed, 16572 collected nodes (16476 + 96).
- `uv run python scripts/check-test-duplicates.py`: passed, zero duplicate groups.
- `git diff --check`: passed.
- Negative control (`repair-inspection-negative.log`): temporary in-process truncation of `InMemoryRunStore.list_by_status` after its first page makes `test_recovery_inspection_measurements[memory-own-repair-1-1-1]` fail at `assert repairs == 1` (observed 0). Original method restored; no tree mutation. This guards against silently losing later repairable residue, not an invented total-work ceiling.
- Re-executed the prior report's full focused core acceptance command, PostgreSQL enabled: **203 passed, 4 pre-existing xfailed, no skips** (`repair-acceptance.log`). Xfails retain superseded immediate Graph settlement/claim expectations; none is acceptance evidence and none was altered.
- Re-executed Hive canonical cadence/delegation tests: **21 passed** (`repair-hive.log`).

### PostgreSQL measurements (normal repair, width 3, depth 4)

Each tuple is returned Run-page / NodeRun-list / Attempt-list records; duplicate reads count as work. Point-read counts are separate in raw JSON, not included in these tuples. Every first tick repairs 1; every repeated/fresh-Container tick repairs 0.

| Unchanged pages | First tick records | Repeated = fresh-Container records |
| --- | --- | --- |
| 0 | 1 / 2 / 1 | 0 / 0 / 0 |
| 1 | 2 / 14 / 13 | 1 / 12 / 12 |
| 2 | 3 / 26 / 25 | 2 / 24 / 24 |
| 10 | 11 / 122 / 121 | 10 / 120 / 120 |

At 10 pages the repeated tick also returns 160 Run, 90 NodeRun and 30 Attempt point-read records on PostgreSQL. With width 1/depth 4, its list counts instead are 10 / 20 / 40. Width and historical Attempt depth therefore affect work separately from the repair quota. Both normal and peer-first legs retain the same repeated/fresh-Container counts. These are executed observations, not a performance threshold or authorization to alter #1098 policy.

Final production gates: requested exact Vulture command passed again (1322/1322; `repair-vulture.log`); `uv run python scripts/check-radon-baseline.py` passed (137/137; `repair-radon.log`); `uv run python scripts/check-reachability.py` passed (1403 modules, 169 reviewed unreachable; `repair-reachability.log`). No quality ledger or grant amendments warranted. No production files changed.

## Acceptance ledger and handoff — parent remains BLOCKED

| Retained criterion | This round's executed evidence and remaining limitation |
| --- | --- |
| Bounded/indexed RUNNING candidates and re-derivation | PG backlog and SQLite index tests in acceptance battery passed; new 96-node matrix exercises real candidate API. **A total inspected-work bound is not established**: measured reads grow independently of the repair limit. |
| All required terminal NodeRuns settle without a new Attempt | Both existing real-PG completion windows passed via public Container tick; full physical history/fixed-point assertions and no-dispatch guards passed. |
| Lost frontier with resume_at=None cannot strand indefinitely | Existing PG lost-frontier and active-Attempt protection tests passed; no quiet-period weakening. |
| Canonical/terminal continuation disagreement, including WAITING/PAUSED | Terminal canonical projections passed. Parked characterization preserves unresolved decision states. General parked disposition **UNSATISFIED / DESIGN_BLOCKED** under accepted ADR-08f0; actual walker reachability of all four parked pairs remains **UNVERIFIED**. |
| QUEUED continuation / RUNNING checkpoint-1 | PG expired-claim recovery/resume and live-claim refusal passed. No immediate no-claim rewrite claimed. |
| Persistence failure after successful runtime | Chat post-dispatch recording-failure and store-conformance cases passed; universal Graph output preservation/retry-policy behavior **UNVERIFIED**. `execution.py::_settle_provider_success` still has one terminal-write invocation, not the retry claimed in old PR metadata. |
| Chat lease/fence/reclaim and non-swallowed failure | Targeted chat recovery, execution fencing and terminal-write cases passed with PostgreSQL enabled. No unleased ownership inferred. |
| Replica idempotence/fencing | Existing independent-PG convergence/fencing cases passed; new peer-first cases prove observed progress and repeated zero progress with full-history preservation. |
| PG crash/forced-interleaving coverage of each verified window | Existing eleven dual-store spine cases passed, plus new 32 PG measurement nodes. Complete crash-boundary coverage **UNVERIFIED**; new fresh-Container measurements are not process death or pool-restart proofs. |
| Bounded/indexed, not an unbounded historical Run scan | Terminal historical candidate exclusion/keyset traversal passed. 0/1/2/10-page nested work now measured; policy/total bound remains unresolved under #1098. Internal SQL scan cost and other sweep phases **UNVERIFIED**. |
| #804 consumes canonical truth, no private Workspace repair | Existing Hive cadence/delegation suite: 21 passed. Complete downstream acceptance **UNVERIFIED**; no product-private repair introduced. |

Exact local changes (all new):

1. `packages/maistro-core/tests/runs/test_recovery_inspection_budget.py`
2. `docs/testing/inventory-notes/1151-recovery-inspection-budget.md`
3. `docs/testing/1151-repair-20261018-followup.md`

Reproduce measurements with `uv run pytest packages/maistro-core/tests/runs/test_recovery_inspection_budget.py -x -q -s` and `MAISTRO_TEST_PG_DSN` set to the assigned migrated database. Credentials were loaded only into the subprocess environment, never recorded. Complete broader pytest commands are recorded as `COMMAND:` lines in `repair-acceptance.log` and `repair-hive.log`.

Scoped measurement is complete, not parent integration approval. No develop conflict existed, no remote refs fetched, and no issue/PR mutation occurred. Inherited branch diffs outside #1151 were preserved and are not validated by this round. Full monorepo tests were not run; focused core/Hive paths were used as instructed.

Checkpoint: checked 1 assigned issue; done 1 scoped measurement; skipped 0 issues; errors 0 outstanding unexpected validation failures. Parent disposition: BLOCKED. Next: authorized parked-decision disposition, #1098 bound/cursor review using these measurements, and remaining Graph durability/consumer proofs. Do not repeat this measurement as a substitute for resolving those dependencies. Local commit required before handoff.
