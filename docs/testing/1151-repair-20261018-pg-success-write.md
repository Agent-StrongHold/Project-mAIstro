# #1151: PostgreSQL lost-success-write validation

## Scope and decision

Assigned writer worktree `auto-1151`, starting HEAD
`00db4697cf6fb132c7bd88b33c02beb69e776528`; supplied develop base
`0b336e3000b91bd3f404295c9849c3d880b8612b`. The starting tree was clean, without
merge conflicts; no salvage or develop merge was necessary. Only issue #1151
was processed, from the supplied dispatch snapshot; no GitHub actions.

Read root instructions, captured primary issue, previous result/report, accepted
ADR-b36a, ADR-08f0 and ADR-6e2a, production recovery/execution seams and adjacent
tests. Accepted park/pending-decision and canonical checkpoint authority remain
binding. The snapshot explicitly blocks new parked dispositions and scan-work
policy; passing tests cannot remove those design holds.

The exact requested Vulture check passed with **1322 reviewed identities / 1322
findings**, zero unclassified. Therefore no ledger amendment or dead-code repair
is justified. Existing production code remains unchanged.

The actual evidence gap addressed here is narrower: the failed-success-write
frontier guard had only an in-memory proof. Added one PostgreSQL test to the
existing dual-authority crash-window suite, reusing its independent recovery
pool and public Container tick fixture. Inventory delta: core +1.

## Execution checkpoint

Logs are in job `6b34200962704901b21faf8e8e9d6376` under
`/home/dev/maistro/jobs/`. No driver `check-*.log` files were present initially.
New logs below were produced in this round. PostgreSQL uses the assigned
`auto-1151-pg` container; credentials are supplied only through subprocess
environment, not committed.

- `uv sync --locked --extra dev`: passed (`check-sync.log`).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed (`check-vulture.log`).
- `uv run pytest packages/maistro-core/tests/runs/test_pg_spine_crash_windows.py::test_lost_success_write_preserves_live_ownership_then_parks -x -q -ra`, PostgreSQL enabled: **1 passed**, no skips (`check-pg-success-write.log`).

The new test injects an ordinary pre-commit completion-write failure after the
node returns real successful output. Independent reads prove RUNNING physical
and logical ownership, not a contradictory FAILED Run. A tick just before
persisted expiry leaves all canonical records unchanged; a tick exactly at
expiry reclaims and parks; repeating it is a no-op. Identity/ordinal/fence are
preserved and the recovery fixture prohibits new physical work. This is not
proof that uncommitted output is preserved, nor a new retry authorization.

- Negative control (`check-pg-success-write-negative.log`): disable only
  `attempt_executor._frontier_has_active_attempt` in-process. The new test fails
  at its RUNNING assertion with actual FAILED / `PhysicalExecutionError`.
  Original function restored; no production-source edit. This detects the
  named regression rather than merely exercising PostgreSQL fixtures.
- Core acceptance battery with PostgreSQL (`check-core-acceptance.log`):
  **229 passed, 4 existing strict xfails, no skips**, including the new test,
  dual-store spine crash windows, chat/execution fencing, cross-store repair,
  checkpoint/active-frontier guards, index coverage, completion budgets and
  parked-conflict matrix. Exact command is the log's first line. Existing
  strict xfails were not edited and are not counted as acceptance proof.

- Full changed PostgreSQL crash-window file run independently: **12 passed**,
  no skips (`check-pg-windows.log`); exact collected IDs recorded in
  `check-pg-window-collection.log`.
- `git diff --check`: passed.
- Inspection matrix with PostgreSQL: **96 passed**, no skips
  (`check-inspection.log`). This measures the known work-growth limitation;
  passing it does not establish a total-work bound.
- Hive canonical recovery cadence/delegation: **21 passed**, no skips
  (`check-hive.log`).
- `uv run ruff check .`: passed (`check-ruff.log`).
- `uv run ruff format --check .`: passed, 3312 files (`check-format.log`).
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  passed, 16573 nodes including the +1 delta (`check-inventory.log`).
- `uv run python scripts/check-test-duplicates.py`: passed, zero duplicate
  groups (`check-duplicates.log`).

## Acceptance ledger

All executed evidence below is from this round. Historical claims and strict
xfails are not used as proof. Full-tree pytest was not run; scope is relevant
core and Hive suites with both canonical PostgreSQL authorities where supported.

| Retained criterion | Executed evidence and limitation |
| --- | --- |
| Indexed/bounded RUNNING candidates and re-derivation | PostgreSQL backlog and SQLite index tests pass in core battery. Pagination is proven, but total inspected-work bound remains **UNVERIFIED**. |
| All required NodeRuns terminal settles without a new Attempt | PostgreSQL committed-Attempt and last-NodeRun crash tests pass through public Container tick with unchanged physical history. |
| Lost frontier / `resume_at=None` does not strand | PostgreSQL lost-checkpoint recovery and frontier guard pass, preserving the existing quiet-period protection. |
| Terminal continuation disagreement, including WAITING/PAUSED | Terminal canonical projection repair passes. Parked matrix preserves genuine pending decisions but injects conflicting terminal projections. General parked repair remains **UNSATISFIED / DESIGN_BLOCKED**, natural reachability of all pairs **UNVERIFIED**. |
| QUEUED-continuation / RUNNING checkpoint-1 | PostgreSQL elapsed-claim recovery and live-claim refusal pass. No claim-free immediate transition is claimed. |
| Successful-runtime persistence failure preserves result/retry policy/recoverability | New PostgreSQL proof verifies single execution/write attempt, live ownership, reclaim/parking and fixed point. It explicitly demonstrates uncommitted output is absent, not preserved. Universal Graph output preservation/retry-policy acceptance remains **UNVERIFIED**. |
| Chat canonical lease/fence/reclaim, non-swallowed terminal-write failure | Chat recovery, execution and fencing suites pass in the PostgreSQL-enabled core battery. No ownership inference for unleased work added. |
| Idempotence/fencing across replicas | Existing independent-pool convergence/fencing cases and new independent-pool reclaim/fixed-point case pass. |
| PostgreSQL crash/interleaving proof for every window | Existing dual-store windows plus new ordinary failure injection pass. Complete crash coverage remains **UNVERIFIED**; independent pools are not OS process-death proof, and this new test does not cover uncertain commit acknowledgement. |
| Sweep bounded/indexed, not all historical Runs | Candidate historical-exclusion/index tests pass; inspection matrix confirms unchanged prefixes and nested history still cost reads independent of repair count. Total-work bound unresolved under #1098. |
| #804 consumes canonical truth without product-private repair | 21 Hive cadence/delegation tests pass. Complete #804 acceptance remains **UNVERIFIED**; no private recovery authority introduced. |

## Remaining blockers and handoff

Production `canonical_store.py::_reconcile_terminal_graph` still requires a
RUNNING canonical Run; `_reconcile_terminal_spine` projects terminal canonical
truth but cannot authorize a pending-decision bypass. ADR-08f0 overrides any
interpretation of #1151 that would simply force WAITING/PAUSED to terminal.
`container.py::_reconcile_unreconciled_terminal_attempts` still bounds repairs,
not inspected pages/NodeRun/Attempt history. No new cursor/fairness policy is
authorized by this round. `runs/execution.py::_settle_provider_success` still
performs one completion write, preserving the chat no-inline-retry contract;
this test does not recover lost Graph output.

The requested exact-debt-ledger repair is **not needed** on this head. No ledger,
grant, scheduler, authorization path, canonical execution authority or
production source changed. The previous BLOCKED verdict cannot be removed by
this scoped test repair. Next work requires accepted parked-decision mapping,
#1098 scan-bound policy, and the missing Graph durability/downstream proofs.
No merge, deployment or issue closure is authorized.

Changed files in this round:

1. `packages/maistro-core/tests/runs/test_pg_spine_crash_windows.py`
2. `docs/testing/inventory-notes/1151-pg-lost-success-write.md`
3. `docs/testing/1151-repair-20261018-pg-success-write.md`

Checkpoint: checked 1 issue; done 1 scoped coverage repair; skipped 0 issues;
errors 0 unexpected validation failures (negative-control failure intentional).
Local commit identity and clean-status confirmation are recorded in the worker
handoff. No push or GitHub mutation. Writer verdict: **BLOCKED** for parent
acceptance; scoped coverage repair is ready for review only.

