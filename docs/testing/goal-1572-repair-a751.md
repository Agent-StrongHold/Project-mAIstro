# Issue #1572 repair — job a751e6c583954d039151b4eb124ddb8c

## Frozen scope and initial state

- Sole item: issue #1572, branch `auto-1572`, assigned worktree
  `/home/dev/Git/wt/auto-1572`.
- Starting HEAD: `ee80944315d0991f54c1ff553f01748a931350c8` (verified).
- Dispatch base: `8fbbbfb91d78d30d756cf675b7b1a4c1ccff06e5` (resolved by diff).
- Initial working tree clean; no incoming edits to salvage.
- Evidence snapshot: supplied dispatch-context.json and check-0 through check-4.log;
  no remote re-enumeration planned.
- Repair surfaces frozen to the Goal implementation, adjacent Run/container and
  migration tests, relevant CI gate scripts/workflows (inspection only),
  `quality/vulture-baseline.json` only if the required scan establishes a need,
  and this validation report. No unrelated branch differences will be altered.
- Assumption: this is the writer repair lane, not the read-only verifier lane.
  The explicit vulture exception does not authorize execution-lifecycle grants
  or other ledger changes. Previously reported failures must be reproduced.

## Progress

Initial inspection confirms this is a large pre-existing branch, with unrelated
base differences. Those differences are preserved, not repaired in this item.
Validation and acceptance results follow below as executed.

### First-hand blocker reproduction

- Supplied check logs: dependency sync, Ruff lint/format and suite inventory pass;
  focused Goal/parity tests report **55 passed, 16 skipped**. Skips are not proof
  of PostgreSQL acceptance.
- Required CI-exact vulture scan: **exit 0**, 1326 reviewed identities / 1326
  findings, zero unclassified. No ledger amendment is warranted.
- `uv run python scripts/check-execution-lifecycles.py`: **exit 1**, 19 trusted
  lifecycles vs 20 discovered; `maistro.goals.model::GoalStatus` is absent from
  the trusted base with no already-landed authorization. Its actual selected
  base is `e46ad6708fda20f76b8915679ef701f3ddb6b7e2`, also confirmed by
  `git merge-base HEAD origin/develop`, not the dispatch comparison SHA.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format
  '{{.ServerVersion}}'`: **exit 1**, cannot connect to the daemon. Durable
  PostgreSQL acceptance cannot be inferred from the available test skips.
- State: the reported lifecycle blocker is reproduced, not a vulture finding.
  No authorized in-lane code/ledger repair has been established; do not disguise
  GoalStatus to evade the lifecycle scanner. Continue only bounded acceptance
  validation and record the required external handoff.

### Focused validation reruns

- `uv run pytest packages/maistro-core/tests/goals
  packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py
  -x -q -rs`: **55 passed, 16 skipped**, exit 0. PostgreSQL DSN / database URL
  unset; the skipped backend and parity legs remain unverified.
- `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py
  tests/migrations/test_migration_chain.py -x -q -rs`: **2 passed, 23 skipped**,
  exit 0. Live migration tests require the unavailable PostgreSQL test server.
- `uv run pytest tests/test_check_execution_lifecycles.py -x -q`: **28 passed,
  1 failed**, exit 1. `test_the_shipped_ledger_matches_the_shipped_code` at
  `tests/test_check_execution_lifecycles.py:374` independently reproduces the
  same missing GoalStatus authorization. This is a policy failure, not an
  import/dependency failure.
- `uv run ruff check .`: **PASS**. `uv run ruff format --check .`: **PASS**,
  3205 files formatted.
- `uv run python scripts/check-m1-convergence-freeze.py --base
  8fbbbfb91d78d30d756cf675b7b1a4c1ccff06e5`: **PASS**, no unapproved architecture
  island. Does not override the separate lifecycle policy failure.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`:
  **exit 1**, nine producer results missing (docker-build, durable-events,
  Hive backend/UI e2e, MinIO, PostgreSQL 17/18, strike-ladder, wheel-imports).
  This is a fail-closed local evidence check, NOT proof that those jobs failed
  remotely, nor a diagnosis of the reported remote aggregation failure.
- `uv run alembic heads`: **PASS**, single head `062`.

### Architecture reconciliation

Read the repository instructions, documentation authority map, and accepted
ADRs `ADR-081226-9944`, `ADR-081226-a66b`, `ADR-092326-97c4`. Goal desired-state
lifecycle is separate from Run execution lifecycle; it must not be hidden or
replaced to bypass the ratchet. The canonical WorkspaceAuthorizer remains the
permission seam (`goals/authorization.py`); the backend selector refuses missing
PostgreSQL Goal tables rather than introducing a process-local authority.
No architecture, lifecycle, authorization, gate, grant or ledger changes are
made in this repair. The vulture exception is unused because its scan passes.

## Acceptance evidence at the frozen HEAD

All test references below are under `packages/maistro-core/tests/goals` unless
otherwise specified. Passing backend claims are limited to memory and SQLite;
all PostgreSQL legs remain **UNVERIFIED**.

| Criterion | Executed evidence and limits |
| --- | --- |
| Goal / immutable GoalRevision round-trip on three backends | Shared conformance `test_goal_round_trips_through_the_backend` passes on memory/SQLite, inspecting revision content and history. PostgreSQL skipped. |
| Append-only, stale-revision refusal, one concurrent winner | `test_goal_revision_chain_is_append_only_with_one_cas_winner`, lifecycle and concurrent-transition tests pass on memory/SQLite, checking original content and exactly one successful write. PostgreSQL skipped. |
| Subgoal lineage and explicit recorded Agent reassignment | Shared lineage and reassignment tests pass on memory/SQLite, including rejected foreign Project/Workspace parents and old/new owner transition records. PostgreSQL skipped. |
| Run admission and immutable historical binding | `test_run_goal_binding.py` passes admission, storage round-trip, terminal-transition preservation and paired-field validation on memory/SQLite. The tested fixed binding does not demonstrate preservation when the Goal advances after admission: that scenario is UNVERIFIED. PostgreSQL skipped. |
| Two principals isolated; foreign indistinguishable from missing | Shared conformance scoped tests pass for both local backends through `WorkspaceAuthorizer`, comparing exception type/message and asserting refused writes change nothing. PostgreSQL skipped. |
| Shipped Container wiring and both production compositions | `test_goal_wiring.py` calls real `create_container` and exercises its principal-carrying seam. Source reachability: `container.py:2362,2648`, server `maistro_server/main.py:344`, Hive `backend/adapters/maistro_core.py:195`. Backend-selection stubs are not live PostgreSQL evidence. Actual durable startup/restart of both products is UNVERIFIED. |
| Restart and recover same Goal, revisions and bound Run | `test_goal_restart_readback.py` passes SQLite store close/reopen. It directly constructs stores, not Hive/server product compositions; deployed durable composition restart and PostgreSQL remain UNVERIFIED. |
| No GoalRun, alternate executor or private Goal lifecycle | Convergence freeze passes against dispatch base. Lifecycle policy gate independently fails and must not be overridden by the freeze result. |
| Preserve user-model 056 / planner 057 identities and append fresh migration | Two static installed-base tests pass, including historical-byte comparison and ancestry assertions. `alembic heads` reports only 062. Central allocation coordination is UNVERIFIED. |
| Populated actual c560d4c and 4675101 snapshots forward-upgrade without reset/restamp | Both live snapshot migration tests skipped: PostgreSQL 17 and 18 UNVERIFIED. |
| Upgrades preserve facts/keys/Run data, planner indexes/constraints and create usable Goal tables; reopen provenance | PostgreSQL migration/readback legs skipped: both supported majors UNVERIFIED. |
| Fresh install, unique head/IDs, supported downgrade/refusal, reapplication, older quota-door history | Static identity/ancestry evidence passes; live chain legs skipped. PG17/PG18 downgrade/reapplication and complete earlier-history compatibility audit UNVERIFIED. |

## Disposition and handoff

**BLOCKED**, not an integration approval. The only changed file in this round is
this report. No tests were added or changed; inventory delta is zero, so no new
inventory note is required. Driver inventory check passed with 15,797 core tests.

The observed failure cannot be repaired under this lane's grant/ledger policy.
`scripts/ratchet_provenance.py:478` loads authorizations from the trusted base;
a candidate-only grant would not work even if it were permitted. Required next
step: the governance owner must resolve GoalStatus authorization independently
on the trusted base, then a subsequent authorized synchronization can validate
the candidate. Do not remove or disguise the Goal lifecycle to evade the gate.

Separately, restore PostgreSQL test service availability and run the skipped
PG17/PG18 conformance, migration and durable product restart criteria. Obtain
actual specialized producer results before declaring integration-scope repaired.
The supplied snapshot does not establish current-head producer success, and the
local aggregator's missing inputs do not identify the remote failed producer.
No remote fetch, push, PR mutation, merge, gate weakening or work deletion was
performed. Existing branch work is preserved.

Progress: checked 1 assigned item; done 0 repairs; skipped 0 items; blocked 1.
Next: trusted-base policy resolution and service-backed acceptance validation.
