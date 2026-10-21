# Issue #1151 repair checkpoint

Scope snapshot: issue #1151 only, assigned branch `auto-1151`, starting HEAD
`f72d86d26ac32640b26522dc14e54f4e7ca85963`, base
`ce2048cd2430bf99a5896b229fd1999976dc07dd`. Worktree initially clean.
Process the existing issue diff, adjacent execution/reconciliation tests and
accepted ADRs; no other issues or PRs. CI repair also permits reviewed changes to
`quality/vulture-baseline.json`. Exact additional file targets will be recorded
before editing after architecture inspection.

Prior verifier result read: two concerns are terminal persistence retry and
parked canonical/terminal continuation disagreement. These are evidence to
investigate, not permission to override ADR authority. Current job directory has
no check-*.log files; validation will be run locally. Prior checks are not assumed
true. Ambiguity: lane is a writer repair, not a read-only verifier; proceed as
writer and commit locally.

Initial validation: `uv sync --locked --extra dev` passed. Exact requested
vulture scan (`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'`) passed: 1322 reviewed identities,
1322 findings, no unbanked identities. No ledger amendment is justified.

Captured issue body explicitly labels parked-conflict repair DESIGN_BLOCKED,
requiring preservation of pending decisions and characterization only. Therefore
the prior verifier's demand for terminalizing those rows cannot be implemented as
an authorized fix. Full parent acceptance remains blocked; characterization is
not reconciliation. Also, source inspection reveals the existing parked test's
`postgres` fixture uses InMemoryRunStore, so it is not a dual-PG durability proof.

Repair target snapshot (no additional runtime changes):
- `packages/maistro-core/tests/graph/durable_runs/test_parked_terminal_continuation_disposition.py`:
  replace the mixed PG fixture with canonical PgRunStore + PgGraphContinuationStore,
  read/reconcile through an independent pool, evaluate pending timers at the explicit
  test clock, and retain complete Run/NodeRun/Attempt/continuation snapshots.
- `docs/testing/inventory-notes/1151-parked-terminal-continuation-disposition.md`:
  correct proof scope and backend description; unchanged 15-node inventory delta.
- This checkpoint/report.

Accepted ADRs b36a, 08f0 and 6e2a read in full. They require proven lease
ownership, preservation of pending decisions, and canonical RunStore plus Graph
continuation authority. No in-line terminal-write retry or new parked disposition
will be introduced. The fixture constructs split-state inputs; it does not prove
a production walker can reach every synthetic row. Wording will say so.

Environment: existing lane-specific Docker container `auto-1151-pg` is running on
127.0.0.1:18551. No develop-sync conflict is present. Missing optional local
`tests/graph/durable_runs/conftest.py`: not found; skipped (shared core conftest read).

Repair validation checkpoint: parked characterization suite executed with the
lane PostgreSQL DSN, schema 063: **15 passed**, including all 5 dual-PG cases.
Full node IDs and output: job directory `repair-parked.log`. Recovery now resolves
both committed halves through an independent pool and compares complete history;
no runtime disposition change. The previous mixed-backend proof is explicitly
superseded in the inventory note. Initial edit call rejected an ambiguous match
without modifying the file; the corrected single-call edit succeeded.

Independent-read negative control: an in-process pytest plugin replaced only
the PG test's writer RunStore with InMemoryRunStore, retaining independent PG
recovery. `postgres-waiting-completed` fails at the new pre-recovery read with
`RunIntegrityError: graph continuation ... has no canonical Run` (expected).
No source file was reverted or mutated for this probe. See
`repair-mixed-backend-negative.log`. The intact fixture passes all 15 nodes.

Combined core acceptance command (full command recorded below) ran with real
PostgreSQL: **203 passed, 4 xfailed**, no skips, in 17.14s. Includes the issue's
seven-file baseline, both chat recording-failure/conformance classes, and all
five lane files. The four pre-existing strict xfails describe superseded
immediate-recovery assertions; they are not counted as successful acceptance
proof. Output: `repair-acceptance.log`.

Quality battery: all eight commands passed (`repair-gates.log`): root ruff lint,
root ruff format check (3311 files), scoped core suite inventory (16476 nodes),
exact vulture (1322/1322), radon (137/137), reachability, duplicate-test content
(0 groups), promotion surface. No ledger or grant changes.
Hive issue baseline (`test_canonical_recovery_cadence.py` and
`test_dag_recovery.py`) passed **21 tests** (`repair-hive.log`). This proves
existing delegation/cadence paths, not the whole #804 consumer acceptance.

## Acceptance disposition

The **parent remains BLOCKED**. This is a scoped proof repair, not integration
approval. The prior verifier's two concerns reconcile as follows: the in-line
retry claim is stale PR metadata, not delivered behavior (the existing inventory
note already discloses it); parked/terminal disagreement is still unrepaired,
and cannot be solved by bypassing the accepted pending-decision table. No
GitHub mutation or new recovery authority is appropriate.

| Parent criterion | Executed evidence and limitation |
| --- | --- |
| Bounded/indexed RUNNING candidates | PG backlog case in `test_pg_spine_crash_windows.py` and `test_sqlite_recovery_index.py` passed. This proves page work, not a uniform bound on nested NodeRun/Attempt reads. |
| Terminal required NodeRuns settle without new Attempt | `test_run_terminal_recovery_acceptance.py`, crash-window invariants and PG last-NodeRun commit case passed. The old immediate Graph-settlement assertion is xfailed, not evidence. |
| Frontier lost with `resume_at=None` | PG frontier/checkpoint case and live-Attempt guard passed; quiet-period protection retained. |
| WAITING/PAUSED x COMPLETED/FAILED disagreement | **UNSATISFIED / DESIGN_BLOCKED**. All 15 characterization nodes passed, preserving rather than settling the pending decision. Actual walker reachability of all four synthetic rows remains **UNVERIFIED**. Terminal canonical -> stale continuation repair is independently covered by the passing canonical-store suite. |
| QUEUED continuation / RUNNING checkpoint-1 | PG elapsed-claim and live-claim cases passed; immediate no-claim rewrite remains a pre-existing strict xfail, not authorized behavior. |
| Successful execution followed by persistence failure | Chat post-dispatch class (18 nodes) and backend conformance (12 nodes), plus Graph live-Attempt guard passed. Chat returns the answer once and records the failure; the guard leaves Graph work recoverable. No in-line retry claim. Universal result-preservation across every Graph crash remains **UNVERIFIED**; lost uncommitted output is not fabricated as success. |
| Chat lease/fence/reclaim and visible write failure | `test_chat_attempt_recovery.py`, `test_execution_fencing.py`, and both chat classes passed with PG configured; leaseless work is not inferred dead by a sweep. |
| Multi-replica idempotence and fencing | PG two-replica convergence case and execution fencing suite passed. No claim of exhaustive interleaving coverage. |
| PostgreSQL crash coverage for each verified window | Nine PG spine cases passed, as did all five now-dual-PG parked cases. **Full criterion UNVERIFIED**: parked cases are constructed inputs, not production crash injection; the R7 terminal replay helper copies enumeration rather than calling Container; no OS-kill proof was run. |
| Bounded work, no historical full scan | Indexed page/backlog tests passed; broader 0/1/2/10-page nested-work measurement requested by the parent is **UNVERIFIED**. |
| #804 consumes canonical truth | 21 existing Hive cadence/delegation tests passed; complete #804 consumer proof **UNVERIFIED**. |

## Commands / artifacts

All logs are in `/home/dev/maistro/jobs/1b64536dc3ae4712b7b0cc4b12629fde`.
PG runs used the existing lane container `auto-1151-pg` with schema 063 and
`MAISTRO_TEST_PG_DSN` set; credentials are not recorded here.

- `uv sync --locked --extra dev`: pass.
- `uv run ruff format packages/maistro-core/tests/graph/durable_runs/test_parked_terminal_continuation_disposition.py`: formatted the changed test only.
- `uv run pytest packages/maistro-core/tests/graph/durable_runs/test_parked_terminal_continuation_disposition.py -x -vv`: 15 passed, exact node IDs in `repair-parked.log`.
- In-process `pytest.main` negative-control plugin, same file with
  `-k 'postgres and waiting and completed' -x -q`: expected single failure;
  wrapper asserted TESTS_FAILED and exited 0 (`repair-mixed-backend-negative.log`).
- Combined command below: 203 passed, 4 pre-existing xfails (`repair-acceptance.log`).
- `uv run --frozen pytest packages/hive-conductor/backend/tests/test_canonical_recovery_cadence.py packages/hive-conductor/backend/tests/test_dag_recovery.py -x -q -ra`: 21 passed (`repair-hive.log`).
- `uv run ruff check .`; `uv run ruff format --check .`: pass.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: pass.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: pass, no ledger changes required.
- `uv run python scripts/check-radon-baseline.py`, `check-reachability.py`,
  `check-test-duplicates.py`, `check-promotion-surface.py` (each with the same
  `uv run python scripts/` prefix): all pass (`repair-gates.log`).
- `git diff --check`: pass.

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
```

Scope checkpoint: checked 1 issue, scoped proof repair done 1, skipped 0 issues,
errors 0 unexpected validation failures. Next: authorized parent design/consumer
proof; do not infer merge-readiness from this scoped repair. Only the three
snapshotted files changed, with no runtime/gate/ledger/grant modifications.
