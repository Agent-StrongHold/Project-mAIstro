# #1151 repair verification — 956dad7e

## Scope and disposition

**BLOCKED; no evidence-backed CI repair was available.** Assigned branch/worktree:
`auto-1151`; inspected source HEAD:
`1a575011874889951a573a91686aeee9267ff863`. The worktree was clean at entry.
Only issue #1151, its supplied dispatch evidence and its authorized vulture repair
were processed. No GitHub mutation, push, activation or policy change occurred.
The supplied develop base `35a72ff54d4f09429cf0b9349ecff7f3e9396f5d` resolves but
`git merge-base --is-ancestor <base> HEAD` exits 1. This is exact assigned-head
validation, not validation of an integrated develop tree. There were no merge
conflicts to resolve; the prior block concerns acceptance/policy, not a failed
sync. No merge was attempted.

The exact requested vulture invocation passes: **1322 findings / 1322 reviewed
identities**, zero unclassified. There are no unbanked or eliminated identities
to amend. Changing the ledger just to produce a repair would be unjustified.
No code, tests, ledgers or grants changed. This evidence report is the only change;
there is no test inventory delta.

Read repository instructions, supplied issue body/comments and prior result, and
accepted ADR-082526-b36a, ADR-082826-08f0 and ADR-083026-6e2a. The supplied job had
no driver `check-*.log` files at entry. Earlier verification claims were not used
as executed evidence: all results below were obtained again on this source.

## Actual remaining blockers

- `packages/maistro-core/src/maistro/graph/durable_runs/canonical_store.py:640`
  requires canonical RUNNING before applying terminal Graph settlement. The four
  WAITING/PAUSED × COMPLETED/FAILED disagreements remain unchanged. The tests at
  `packages/maistro-core/tests/graph/durable_runs/test_parked_terminal_continuation_disposition.py:251`
  execute real parking, then **inject** the contradictory projection. They prove
  preservation/isolation, not production reachability or repair of those rows.
  ADR-08f0 requires the pending decision before terminalization; broadening the
  guard would bypass that requirement. The supplied issue explicitly holds this
  repair pending disposition/reachability review. No new disposition is assumed.
- `packages/maistro-core/src/maistro/container.py:1372` loops until the **repair**
  quota is spent; `:1336` and `:1304` read nested NodeRun/Attempt histories. Passing
  `test_recovery_inspection_budget.py` measures increasing reads for unchanged
  prefixes of 0/1/2/10 pages, including zero-repair repeat/fresh-Container ticks.
  Paging is not a total inspected-work bound. The issue assigns scan-policy
  review to #1098; this round does not introduce a competing cursor or scheduler.
- `packages/maistro-core/src/maistro/runs/execution.py:751` delegates terminal
  persistence once. `graph/durable_runs/attempt_executor.py:862` resolves a lost
  acknowledgement from this Attempt's persisted COMPLETED result; it explicitly
  does not retry the write or fabricate success from uncommitted output. The old
  PR terminal-write-retry claim is not true of this source. A Graph result lost
  before commit is not universally preserved by the passing recovery tests.
- Server source search for the canonical recovery seams found only a chat API
  docstring, not a direct recovery tick caller. Hive cadence proof is not proof
  of integrated server activation or the complete #804 acceptance contract.

These are not develop-sync conflicts or vulture failures. They cannot safely be
resolved by reversing preservation assertions, removing guards, adding an
unapproved disposition or changing fairness policy. The previous block remains
substantive rather than a CI ledger problem.

## Executed validation

Logs: `/home/dev/maistro/jobs/956dad7e95fb4c2faf41bf5711d84e55/check-*-worker.log`.
PostgreSQL used the existing isolated `auto-1151-pg` service. Its connection
configuration was inspected and supplied privately through `MAISTRO_TEST_PG_DSN`;
no credentials were written to this report or logs. PG cases use actual
PgRunStore and PgGraphContinuationStore with independent pools. These are
API-commit-boundary injections, not OS process-kill/network-COMMIT experiments.

```sh
uv run pytest packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/runs/test_pg_spine_crash_windows.py packages/maistro-core/tests/runs/test_chat_attempt_recovery.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/runs/test_crash_window_invariants.py packages/maistro-core/tests/runs/test_recovery_completion_budget.py packages/maistro-core/tests/runs/test_run_terminal_recovery_acceptance.py packages/maistro-core/tests/runs/test_recovery_inspection_budget.py packages/maistro-core/tests/runs/test_sqlite_recovery_index.py -x -q -ra
```

**944 passed, 4 existing strict xfails, no skips, 135.51 s.** Xfails cover the
historic immediate terminal-node settlement, immediate empty-frontier eligibility,
immediate terminal projection settlement and claim-free checkpoint-1 assertions
in `test_canonical_durable_store.py`. They are not acceptance proofs and were not
changed. The prospective `test_pg_continuation_crash_windows.py` from the issue
was not found (inspection grep exited 2); it was not passed to pytest or counted
as verified.

| Command | Outcome |
| --- | --- |
| `uv run pytest packages/hive-conductor/backend/tests/test_canonical_recovery_cadence.py packages/hive-conductor/backend/tests/test_dag_recovery.py -x -q -ra` | 21 passed, no skips |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed; 3328 files |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Passed; 1322/1322 identities |
| `uv run python scripts/check-radon-baseline.py` | Passed; 137/137 blocks, no drift |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Passed; 16609 nodes |
| `uv run python scripts/check-test-duplicates.py` | Passed; 1615 files, zero duplicate groups |

Workflow gate arguments were inspected. Full-tree pytest/inventory were not run.
No new test or production fix is claimed, so no fail-before/pass-after result is
claimed either.

## Retained acceptance ledger

| Criterion | Fresh evidence and limit |
| --- | --- |
| Canonical indexed/bounded RUNNING candidates and re-derivation | PG backlog and SQLite index/recovery tests pass. Total inspected-work bound **UNVERIFIED**. |
| Terminal required NodeRuns settle without new Attempt | PG completion-before-reconcile and last-NodeRun-before-Run-write cases pass through the public Container tick. |
| Lost frontier with no resume deadline | PG lost-frontier reconciliation/due-resume case and live-walker guards pass; exhaustive crash positions **UNVERIFIED**. |
| Terminal Graph disagreements, including parked Runs | Terminal canonical projection repairs pass; parked cases preserve pending decisions. General parked repair **UNSATISFIED**. |
| QUEUED continuation / RUNNING checkpoint-1 | PG expired-claim recovery and live-claim refusal pass; claim-free recovery **UNVERIFIED**, existing xfail remains. |
| Runtime success / persistence failure | PG rejected-write, acknowledgement-loss and replay-policy cases pass. Universal preservation of uncommitted output **UNVERIFIED**; no in-line terminal-write retry exists. |
| Chat lease/fence/reclaim and surfaced recording failure; no no-lease sweep inference | Recovery/fencing and PG before/after-commit chat cases pass. Complete HTTP/worker-death matrix **UNVERIFIED**. |
| Idempotence and replica fencing | PG independent-pool convergence, fixed-point assertions and fencing tests pass. |
| PG proof of every window and chat case | Named API-boundary cases pass; complete process-death/COMMIT/interleaving matrix **UNVERIFIED**. |
| Bounded/indexed sweep, no unbounded historical scan | Settled history is excluded; unchanged RUNNING prefixes and nested histories are reread. Total-work bound **UNSATISFIED**. |
| #804 consumes canonical truth, not a private compensator | 21 Hive tests pass. Complete #804/server integration **UNVERIFIED**. |

## Handoff

Checked: 1 assigned issue. Done: current-head evidence and local report. Skipped:
0 issues (one prospective test file absent). Validation failures: 0. Next:
existing parked-disposition and scan-policy owners must resolve the retained
holds; remaining integration/crash proofs must run before parent acceptance.
Passing narrow checks do not authorize merge, integration, activation or closure.
