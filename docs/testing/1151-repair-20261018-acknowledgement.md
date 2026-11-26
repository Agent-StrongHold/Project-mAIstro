# #1151: committed-success acknowledgement repair

## Scope and architectural reconciliation

Assigned worktree/branch: `auto-1151`. Starting HEAD:
`59485af7a99ac1eb303a38ccb26be0d997234891`; supplied develop base:
`0b336e3000b91bd3f404295c9849c3d880b8612b`. Starting tree was clean, with no
merge conflicts. The previous BLOCKED result was a design/acceptance hold, not
a develop-sync conflict. No merge or GitHub mutation was performed.

Frozen item: issue #1151 only. Read repository instructions, the supplied
primary issue snapshot, preceding result/report, accepted ADR-b36a, ADR-08f0 and
ADR-6e2a, and adjacent production/test code. The snapshot explicitly reserves
parked dispositions and scan policy for their existing design owners. No
unconditional WAITING/PAUSED override, scheduler, provenance writer, execution
owner, event authority or product-private recovery path was added.

The newly verified defect is narrower than those holds: ordinary failure after
canonical Attempt completion commits was interpreted as physical execution
failure by the Graph frontier. A successful persisted Attempt could therefore
sit beneath a FAILED Run with `PhysicalExecutionError` naming only the lost
acknowledgement. This violates canonical result authority without requiring any
new recovery disposition to fix it.

Changed surfaces are exactly:

- `packages/maistro-core/src/maistro/graph/durable_runs/attempt_executor.py`
- `packages/maistro-core/tests/runs/test_pg_spine_crash_windows.py`
- `packages/maistro-core/tests/graph/durable_runs/test_frontier_active_attempt_guard.py`
- `docs/testing/inventory-notes/1151-committed-success-acknowledgement.md`
- This report.

The executor records the exact Attempt identity passed to its launch context.
On an ordinary execution-service error it resolves that identity from durable
storage. Only a persisted COMPLETED result can continue through the existing
Graph fold. Missing/unlaunched/non-COMPLETED evidence re-raises the error;
classified infrastructure failure refuses another store read. It cannot adopt
an older successful ordinal or use the in-process result as persisted truth.
There is no completion-write retry or provider redispatch. Chat execution and
its no-inline-retry contract remain unchanged. `_require_node_result` extracts
the existing invariant unchanged to keep complexity within the existing gate.

## Executed evidence

Logs: `/home/dev/maistro/jobs/a83716262554483181a30a8f8969754f/check-*.log`.
No driver check logs were supplied at entry; these logs were produced here.
The existing isolated `auto-1151-pg` container was used. Its connection details
were passed only through subprocess environment; no credentials were committed.

- **Fail-before:** new PostgreSQL test
  `test_committed_success_with_lost_acknowledgement_replays_without_execution`
  fails on the starting production code: persisted COMPLETED Attempt, actual
  FAILED Run / PhysicalExecutionError rather than COMPLETED. An independent
  pool reads the committed payload before the injected OSError. The first test
  draft compared in-process NodeResult versus hydrated JSON directly; correcting
  that fixture assertion to JSON-normalized equality exposed the actual defect.
  Both runs are retained in `check-ack-before.log`.
- **Pass-after:** complete PostgreSQL crash-window file: **13 passed**, no skips
  (`check-ack-after.log`). New case uses `max_steps=1`, exactly one execution and
  one completion write, unchanged persisted identity/ordinal/lease/history,
  accepted canonical outcome, matching terminal continuation and no-op recovery.
  This models an API-boundary lost acknowledgement, not an actual dropped network
  COMMIT response or OS process death.
- Guard test file: **11 passed**, including ten new cases. Negative cases cover
  absent/every non-COMPLETED Attempt, unlaunched identity, infrastructure failure
  and persisted physical completion carrying logical failure.
- Broad PostgreSQL-enabled core battery: **941 passed, 4 unchanged strict
  xfails, no skips** (`check-core-acceptance.log`). Exact command:

  ```sh
  uv run pytest packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/runs/test_pg_spine_crash_windows.py packages/maistro-core/tests/runs/test_chat_attempt_recovery.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/runs/test_crash_window_invariants.py packages/maistro-core/tests/runs/test_recovery_completion_budget.py packages/maistro-core/tests/runs/test_run_terminal_recovery_acceptance.py packages/maistro-core/tests/runs/test_recovery_inspection_budget.py packages/maistro-core/tests/runs/test_sqlite_recovery_index.py -x -q -ra
  ```

- Hive canonical delegation/cadence: **21 passed**, no skips (`check-hive.log`):
  `uv run pytest packages/hive-conductor/backend/tests/test_canonical_recovery_cadence.py packages/hive-conductor/backend/tests/test_dag_recovery.py -x -q -ra`.
- `uv run ruff check .`: passed (`check-ruff.log`). Initial implementation failed
  complexity checks; extraction fixed the code, without exemptions/gate changes.
- `uv run ruff format --check .`: passed, 3312 files (`check-format.log`).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed, **1322 findings / 1322 reviewed identities** (`check-vulture.log`). No retained identity required a ledger amendment; no ledger/grant edited.
- `uv run python scripts/check-radon-baseline.py`: passed, 137 reviewed blocks,
  no regressions/new/stale entries (`check-radon.log`). An exploratory `--help`
  invocation failed because the script passes arguments to Radon and expects
  JSON; this is not a gate failure. The actual CI invocation above passed.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  passed, **16584** collected nodes, matching the +11 note (`check-inventory.log`).
- `uv run python scripts/check-test-duplicates.py`: passed, zero duplicate groups
  (`check-duplicates.log`).
- `git diff --check`: passed (`check-diff.log`). Changed test files' collected
  node IDs are recorded in `check-new-collection.log`.

## Retained acceptance matrix

Strict xfails are not acceptance proof. All passing evidence below was executed
in this round. Full-tree tests were not run.

| Criterion | Evidence / limitation |
| --- | --- |
| Bounded/indexed RUNNING enumeration and re-derivation | PG backlog, SQLite index, terminal-recovery tests pass. Total inspected-work bound remains **UNVERIFIED**. |
| Required terminal NodeRuns settle without another Attempt | PG completion and last-NodeRun crash tests pass through public Container tick, unchanged Attempt history. |
| Lost frontier / resume_at=None cannot strand indefinitely | PG lost-checkpoint test and canonical recovery tests pass, retaining quiet-period/live-walker guards. |
| Terminal continuation disagreement, including WAITING/PAUSED | Terminal canonical projection repairs pass; parked characterization preserves pending decisions. General parked-conflict repair remains **UNSATISFIED / DESIGN_BLOCKED**. |
| QUEUED-continuation / RUNNING checkpoint-1 | PG elapsed-claim repair and live-claim refusal pass. No claim-free immediate settlement is claimed. |
| Successful-runtime persistence failure, result/retry/recoverability | New PG fail-before/pass-after proves committed output survives lost acknowledgement without redispatch/write retry. Existing pre-commit failure proof still parks without fabricating output. Universal uncommitted-result preservation remains **UNVERIFIED**. |
| Chat lease/fence/reclaim and non-swallowed write failure | Chat recovery and execution-fencing suites pass. No new ownership inference or inline retry; full #1170 terminal-write coverage **UNVERIFIED** in this battery. |
| Idempotence and replica fencing | Independent-pool convergence tests, new fixed-point assertions and execution-fencing suites pass. |
| PostgreSQL proof for every crash window | PG suite passes; complete process-death/network-COMMIT/interleaving coverage remains **UNVERIFIED**. |
| Sweep bounded/indexed, not whole history | Candidate/index and inspection-matrix tests pass. Container still bounds repairs rather than total inspected rows/pages; total-work claim remains **UNSATISFIED** under #1098. |
| #804 consumes canonical truth | 21 Hive cadence/delegation tests pass; complete #804 acceptance remains **UNVERIFIED**. |

## Handoff

Parent verdict remains **BLOCKED**. In particular,
`canonical_store.py::_reconcile_terminal_graph` still excludes parked canonical
Runs; accepted ADR-08f0 prevents treating an arbitrary terminal projection as a
pending decision. `container.py::_reconcile_unreconciled_terminal_attempts`
still scans unchanged prefixes until its repair budget is spent. Neither policy
was changed. Previous reports' blanket statement that acknowledgement loss is
unproven is narrowed by the new API-boundary proof, not replaced with a universal
durability claim.

Checkpoint: checked 1 issue; done 1 focused production repair plus tests;
skipped 0 issues; errors 0 remaining focused validation failures. Remaining
acceptance/design holds are listed above. Commit is local only; no integration,
activation or issue closure is authorized. Commit identity and final clean-tree
confirmation are supplied in the worker response.
