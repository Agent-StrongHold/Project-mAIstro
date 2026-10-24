# #1151 repair: current round

## Frozen scope

- Issue #1151 only; worktree `/home/dev/Git/wt/auto-1151`, branch `auto-1151`.
- Starting HEAD `3212c4beca697a36da1b8efdd6e25383d936d871`; supplied base `140e881808475a4dbec063d19740e1e50c340905`.
- Scope: existing #1151 execution/reconciliation code and adjacent tests, its acceptance documentation, and the explicitly authorized vulture identity ledger repair. No remote mutations or grants.
- Starting worktree clean. Supplied job directory has no `check-*.log` artifacts. Prior result reports unresolved parked/terminal policy and universal post-runtime result preservation; those are not assumed fixed.
- Snapshot source: supplied `dispatch-context.json`; no GitHub refresh.

## Progress

Initial inspection confirms the branch contains previous repair tests and reports, not an execution.py terminal-write retry.

Exact requested vulture command passed: 1322 reviewed identities / 1322 findings, no unbanked or eliminated identities. No ledger amendment is justified. Read accepted ADRs b36a, 08f0 and 6e2a completely. The captured issue explicitly blocks a new parked disposition; preserving pending decisions is mandatory, not a defect to fix by forcing terminal status.

Evidence-backed scoped repair selected: `test_pg_spine_crash_windows.py` duplicates Container's terminal replay enumeration in `_reconcile_terminal_attempts`, and its implementation is not actually verbatim (it counts only parent settlement). Replace that helper with the real public `Container.recover_abandoned_attempts` tick wired to the independent PgRunStore. Strengthen both existing completion-window cases with fixed-point/full-history assertions and dispatch guards. Update its existing inventory note (no new collected nodes). This report, that test file, and `docs/testing/inventory-notes/1151-pg-spine-crash-windows.md` are the exact edit targets; no runtime or policy changes. Other parent acceptance gaps remain explicitly blocked/unverified.

## Executed checkpoints

- `uv sync --locked --extra dev`: passed.
- Existing lane PostgreSQL container `auto-1151-pg` is available on port 18551; credentials loaded in-process from its configuration, not stored in the repository.
- `uv run pytest packages/maistro-core/tests/runs/test_pg_spine_crash_windows.py -x -vv`: **11 passed**, no skips. Both repaired cases now use the public Container tick on independent PostgreSQL connections, at limit=1, with complete physical-history/fixed-point assertions. Exact nodes: job `repair-pg-spine.log`.
- Negative control: in-process replacement of only `Container._reconcile_unreconciled_terminal_attempts` with a zero-progress async mock makes **both repaired cases fail** at their first-progress assertion. No tree mutation; original method restored. Job `repair-negative-control.log`. This demonstrates sensitivity to the production replay path that the old test-local loop bypassed.
- Root `uv run ruff check .` and `uv run ruff format --check .`: passed (3311 files formatted).
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: passed, unchanged 16476 nodes.
- `uv run python scripts/check-test-duplicates.py`: passed, zero duplicate groups.
- `git diff --check`: passed.

All current-round log names refer to `/home/dev/maistro/jobs/fdbb35f79df640e08ea9e3ac2ac552ae`.

- Combined core acceptance run below: **203 passed, 4 pre-existing strict xfails, no skips** (`repair-acceptance.log`). The xfails encode superseded immediate Graph settlement/claim expectations and are NOT acceptance evidence. No xfail was added, removed or weakened.
- Hive cadence/delegation baseline: **21 passed** (`repair-hive.log`).
- Exact vulture gate rerun passed unchanged 1322/1322 (`repair-vulture.log`). Radon (137/137), reachability, and promotion-surface gates passed. No quality ledger or grant edits.

## Acceptance ledger: parent remains BLOCKED

The scoped proof repair is complete; it does not resolve blocked policy or confer integration approval. No develop-sync conflict was present. Source inspection still shows a one-shot provider-success terminal write in `runs/execution.py::_settle_provider_success`, not an idempotent terminal-write retry. Adding a new retry/disposition policy is not justified by stale PR metadata. Accepted 08f0 and the captured issue require preserving pending decisions.

| Retained criterion | Current executed evidence / limitation |
| --- | --- |
| Bounded/indexed RUNNING candidate enumeration and re-derivation | PG backlog and SQLite index tests passed. Page bounds proven; uniform total Run/NodeRun/Attempt inspection bound **UNVERIFIED**. |
| Required terminal NodeRuns settle without a new Attempt | Both repaired PG completion-window cases passed via the public Container tick at limit=1; full physical history preserved and second tick zero. Terminal recovery acceptance suite passed. |
| Lost frontier with resume_at=None is recoverable | PG frontier case and active-Attempt guard passed without weakening quiet-period protection. |
| WAITING/PAUSED and terminal canonical/terminal continuation disagreement | Terminal canonical projection cases passed. Parked characterization's 15 nodes passed but intentionally preserve disagreement. General parked disposition **UNSATISFIED / DESIGN_BLOCKED**; actual production-walker reachability of all four constructed pairs **UNVERIFIED**. `canonical_store.py::_reconcile_terminal_graph` only accepts RUNNING canonical state. |
| QUEUED continuation / RUNNING checkpoint-1 window | PG elapsed-claim repair/resume and live-claim refusal passed. No immediate no-claim rewrite is claimed. |
| Persistence failure after successful runtime execution | Chat failure/conformance classes and Graph active-Attempt guard passed. Universal Graph result preservation and retry-policy behavior across every crash boundary **UNVERIFIED**; no retry was introduced or claimed. |
| Chat canonical lease/fence/reclaim and visible terminal-write failure | Chat recovery, execution fencing, post-dispatch recording-failure and store conformance suites passed with PostgreSQL enabled. |
| Idempotence/fencing across replicas | Independent-PG concurrent reconciliation and fencing suites passed; repaired completion tests assert complete fixed points. |
| PostgreSQL crash/forced-interleaving coverage for each verified window | Eleven dual-store PG/spine cases and chat PG legs passed. Removed copied Container enumeration. **Complete criterion UNVERIFIED**: spine-only residue is constructed, parked cases do not prove walker reachability, and no OS-process kill executed. |
| No unbounded historical scan | Indexed backlog/page checks passed. The Container replay loop counts repairs, not all inspected rows; requested 0/1/2/10-page nested-work measurements remain **UNVERIFIED**, not an implied constant-work guarantee. |
| #804 consumes canonical truth without private repair | Existing Hive production cadence/delegation tests passed (21); complete #804 consumer acceptance **UNVERIFIED**. |

## Reproduction commands

The following used `MAISTRO_TEST_PG_DSN` from the existing lane database, without recording credentials:

```sh
uv run --frozen pytest \
  packages/maistro-core/tests/runs/test_crash_window_invariants.py \
  packages/maistro-core/tests/runs/test_recovery_completion_budget.py \
  packages/maistro-core/tests/runs/test_run_terminal_recovery_acceptance.py \
  packages/maistro-core/tests/graph/durable_runs/test_cross_store_crash_reconciliation.py \
  packages/maistro-core/tests/graph/durable_runs/test_canonical_recovery_contract.py \
  packages/maistro-core/tests/runs/test_chat_attempt_recovery.py \
  packages/maistro-core/tests/runs/test_execution_fencing.py \
  packages/maistro-core/tests/runs/test_chat_execution.py::TestAPostDispatchRecordingFailureIsNeverRedispatched \
  packages/maistro-core/tests/runs/test_chat_execution.py::TestChatAttemptStoreConformance \
  packages/maistro-core/tests/graph/durable_runs/test_canonical_durable_store.py \
  packages/maistro-core/tests/graph/durable_runs/test_frontier_active_attempt_guard.py \
  packages/maistro-core/tests/runs/test_pg_spine_crash_windows.py \
  packages/maistro-core/tests/runs/test_sqlite_recovery_index.py \
  packages/maistro-core/tests/graph/durable_runs/test_parked_terminal_continuation_disposition.py \
  -x -q -ra
uv run --frozen pytest \
  packages/hive-conductor/backend/tests/test_canonical_recovery_cadence.py \
  packages/hive-conductor/backend/tests/test_dag_recovery.py -x -q -ra
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run python scripts/check-radon-baseline.py
uv run python scripts/check-reachability.py
uv run python scripts/check-promotion-surface.py
```

Changed files: this report, `packages/maistro-core/tests/runs/test_pg_spine_crash_windows.py`, and `docs/testing/inventory-notes/1151-pg-spine-crash-windows.md`. No production, scheduler, authority, lifecycle policy, gate, ledger or grant changes. Existing work preserved.

Checkpoint: checked 1 issue; done 1 scoped proof repair; skipped 0 issues; errors 0 unexpected validation failures. Next: authorized parked-decision design and remaining parent durability/measurement/consumer proofs. Do not reclassify the parent as merge-ready based on these passing focused tests.
