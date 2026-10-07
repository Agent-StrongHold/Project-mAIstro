---
inventory-delta:
  packages/maistro-core/tests: 0
  tests/: 0
---

# #1572 CI repair evidence (2026-10-07)

Frozen scope: issue #1572 only, branch `auto-1572`, starting head
`b4f7380b263cef922deedd7d44b5cfe24748fde2`, develop base
`9bd1a93eefc4e564041b3cc512f20b229cde64b9`. No PR enumeration or remote
mutation. Initial worktree clean. Process the existing Goal implementation,
its adjacent Run/migration/wiring tests, and the named CI gates; change only
files supported by reproduced failures (vulture ledger exception permitted).

Driver logs inspected: dependency sync, lint, formatting, 46 Goal/schema tests
passed with 16 skipped, and core suite inventory passed. These do not establish
PostgreSQL acceptance or resolve the previously reported lifecycle gate.

Assumption: this is a writer CI-repair round, not the read-only verifier role.
No develop-sync conflict exists at entry. Prior report is evidence to recheck,
not permission to introduce a GoalStatus grant or weaken lifecycle policy.

First-hand gate results at the frozen head:
- CI-exact `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1328 reviewed identities,
  1328 findings, zero unclassified/forbidden. No ledger repair is justified.
- CI-exact `uv run python scripts/check-execution-lifecycles.py`: FAIL,
  `maistro.goals.model::GoalStatus` has no already-landed authorization;
  trusted base `9bd1a93eefc4`, 19 classified versus 20 discovered lifecycles.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format
  '{{.ServerVersion}}'`: FAIL, cannot connect to daemon. PostgreSQL acceptance
  remains unverified, not passed by skipped tests.

Focused validation executed independently of the driver:
- `uv run pytest packages/maistro-core/tests/goals
  packages/maistro-core/tests/runs packages/maistro-core/tests/graph/durable_runs
  packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q`:
  1813 passed, 311 skipped, 5 aiosqlite closed-loop worker-thread warnings in
  adjacent Run tests (not claimed as clean teardown).
- `uv run pytest tests/migrations -x -q`: 38 passed, 125 skipped.
- `uv run pytest tests/test_check_execution_lifecycles.py -x -q`: 28 passed,
  1 failed at line 374, the shipped-ledger test reproduces the missing grant.
- `uv run python scripts/check-m1-convergence-freeze.py --base
  9bd1a93eefc4e564041b3cc512f20b229cde64b9`: passed.

Read accepted ADR-081426-1f7c (Attempt execution mechanics), ADR-092326-97c4
(shared PostgreSQL authority), and ADR-091726-7c2a (interview before consumer
commit). No architecture change is needed to address this gate. The lifecycle
is domain state, but the gate still requires trusted-base authorization; changing
its representation to evade discovery would not be a legitimate repair.

Additional executed checks:
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3145 files.
- `uv run alembic heads`: passed, single head `061`.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: passed, 14961 identities, no duplicate evidence.
- `git diff --check`: passed.
- Diff of `quality/ratchet-authorizations.json` and
  `quality/vulture-baseline.json` against the frozen develop base: empty.
  `scripts/ratchet_provenance.py:478` explicitly loads authorizations from the
  base, so the reproduced missing authorization cannot be repaired here.

## Acceptance evidence and limits

All tests below ran in the focused command above; skips are not passes.

| Criterion | Current evidence |
| --- | --- |
| Goal/revision round-trip on three backends | `test_goal_store_conformance.py::test_goal_round_trips_through_the_backend` passes memory/SQLite; PostgreSQL UNVERIFIED. |
| Append-only, stale update refusal, concurrent single winner | `test_goal_revision_chain_is_append_only_with_one_cas_winner`, `test_lifecycle_transitions_cas_and_terminal_is_final`, and `test_concurrent_transitions_have_exactly_one_winner` pass memory/SQLite; PostgreSQL UNVERIFIED. The concurrency test uses one store instance, not independent SQLite writers. |
| Subgoal parent/Project and recorded owner change | `test_subgoal_lineage_preserves_parent_goal_and_project` and `test_agent_reassignment_is_an_explicit_recorded_transition` pass memory/SQLite; PostgreSQL UNVERIFIED. |
| Run admission binding and historical immutability | `test_run_goal_binding.py` passes memory/SQLite binding, terminal-transition preservation, paired-field refusal and no implicit Goal transition. PostgreSQL UNVERIFIED. The suite does not advance a Goal revision after binding a Run, so that exact historical-revision scenario remains UNVERIFIED. |
| Workspace isolation, foreign equals missing | Scoped conformance tests compare exception type/message and refuse mutations through the real `WorkspaceAuthorizer`; memory/SQLite pass, PostgreSQL UNVERIFIED. |
| Shipped composition exposes store | `test_goal_wiring.py` exercises real `create_container` and its authorized seam. Source confirms server `main.py:344` and Hive `adapters/maistro_core.py:194` call this factory, which wires Goals at `container.py:2377`. Both deployed-process compositions UNVERIFIED. |
| No competing execution authority | Convergence freeze passes against frozen base; lifecycle policy gate FAILS separately. |
| Restart readback | `test_goal_restart_readback.py` closes/reopens SQLite connections and reads Goal, revisions, transitions and bound Run. It does not restart a deployed Container/process; deployed restart and PostgreSQL UNVERIFIED. |
| Preserve merged 056/057, append unused centrally coordinated migration | Migration graph and original-snapshot byte checks pass; head 061 follows integrated 060. Central reservation UNVERIFIED. |
| Actual pre-Goal snapshot upgrades | PostgreSQL upgrade fixtures from c560d4c/4675101 skipped; PG17/PG18 installed-base forward upgrades UNVERIFIED. |
| Preserve populated data, indexes, constraints, durable readback after upgrade | Database-dependent migration tests skipped; UNVERIFIED on both majors. |
| Fresh install, unique head, downgrade/refusal, reapplication, older quota history | Identity/head checks pass; live database legs and complete older-history compatibility audit UNVERIFIED. |

## Handoff

**BLOCKED**. The named vulture gate is already green; speculative ledger edits
would be wrong. No production code, tests, ledgers, grants, or gates changed.
Only this evidence/inventory note was added (zero test delta). The actual
integration blocker is the unapproved GoalStatus identity at
`packages/maistro-core/src/maistro/goals/model.py:53`, reproduced by the
CI command and `tests/test_check_execution_lifecycles.py:374`. Integration-scope
itself is a CI aggregation and was not executed locally; no green is inferred.

Next: an authorized owner must independently land the GoalStatus policy grant
on develop before this branch can consume it. Then rerun lifecycle validation,
provision PostgreSQL 17/18, and prove the remaining migration/production
acceptance legs. Do not substitute candidate grants or scanner evasion. The
unavailable Docker daemon is an environment blocker, not evidence of a store
failure. All earlier work is preserved; no GitHub mutations performed.

Progress: checked 1 assigned item, done 0 repairs, skipped 0 items, errors 1
blocking lifecycle policy failure (plus unavailable Docker). Locally commit
this report as the checkpoint; the issue is not ready for integration.

## Recheck at assigned head 8bd7933ed01f (job 61df6df1)

This is a new first-hand check, not reliance on the earlier results above.
Frozen scope remains #1572 only. Starting HEAD was
`8bd7933ed01fd18dff66a5256beff4142074ef84`, with a clean worktree; supplied
base was `b1f17b8d6246d347f617fb2c0b969e6798e0152b`. Their actual merge base
is `9bd1a93eefc4e564041b3cc512f20b229cde64b9`, which the lifecycle gate
selected. The supplied base's authorization file also has no GoalStatus grant.
No merge conflict exists to resolve. No remote enumeration or mutation occurred.

Read the supplied dispatch issue body, prior result, driver check-0 through
check-4 logs, accepted ADRs listed above, and the adjacent Goal authorization,
wiring, model, conformance, binding, restart, and installed-base tests. The
canonical spine and shared PostgreSQL decision stand; the interview ADR governs
the downstream consumer, not a new scheduler or Goal owner in this repair.

Executed again with long timeouts:

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1328 reviewed identities / 1328 findings; zero unclassified or forbidden. No ledger amendment warranted. |
| `uv run python scripts/check-execution-lifecycles.py` | FAIL: GoalStatus has no already-landed authorization, 19 classified / 20 discovered. This is CI's exact command at `.github/workflows/quality.yml:1501`. |
| `uv run pytest tests/test_check_execution_lifecycles.py -x -q` | 28 passed, 1 failed: shipped-ledger assertion at line 374 reproduces the gate. |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/runs packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q` | 1813 passed, 311 skipped, **6** aiosqlite closed-loop worker-thread warnings; output in job `worker-core.log`. |
| `uv run pytest tests/migrations -x -q` | 38 passed, 125 skipped. No live PostgreSQL upgrade claimed. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS, 3145 files. |
| `uv run python scripts/check-m1-convergence-freeze.py --base b1f17b8d6246d347f617fb2c0b969e6798e0152b` | PASS. |
| `uv run alembic heads` | PASS: single head `061`. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 14961 tests, zero duplicate evidence. |
| `git diff --check` | PASS. |
| `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'` | FAIL: cannot connect to Docker daemon. |

### Current acceptance disposition

- **Round-trip, append-only/stale CAS/single winner, lineage/recorded owner
  change, terminal finality, Workspace isolation and foreign=missing:** the
  shared conformance tests passed memory/SQLite again; PostgreSQL UNVERIFIED.
  CAS concurrency uses a single store instance, not independent SQLite writers.
- **Run binding:** real `admit_direct_work` forwards both fields at
  `runs/admission.py:136`; binding round-trip and preservation across terminal
  transitions passed memory/SQLite. PostgreSQL and a Goal revision advanced
  *after* admission remain UNVERIFIED. No implicit Goal transition test passed.
- **Production composition:** Container exposure and principal seam tests
  passed. Source confirms server `main.py:344` and Hive
  `backend/adapters/maistro_core.py:194` call `create_container`, which wires
  Goals at `container.py:2377`. Deployed Hive/server processes UNVERIFIED.
- **Restart:** SQLite store connections close/reopen with Goal revisions and
  bound Run readback passed; this is not a deployed-process restart.
  PostgreSQL and deployed restart UNVERIFIED.
- **Single execution authority:** convergence freeze passed. Separately, the
  required lifecycle policy gate still fails; DOMAIN classification does not
  exempt a new vocabulary from trusted-base authorization.
- **Migration identities:** installed-base graph and snapshot-byte tests passed,
  preserving merged 056/057 and appending Goals as 061 after 060. Central
  reservation UNVERIFIED. Actual c560d4c/4675101 populated upgrades, durable
  post-upgrade readback/data/index preservation, fresh install, downgrade/refusal,
  reapplication on PG17/PG18, and complete older quota-history compatibility
  remain UNVERIFIED because the live database legs skipped.

**Disposition: BLOCKED.** Only this zero-delta evidence note changed; no source,
tests, grants, ledgers, or gates changed. The vulture exception cannot authorize
an execution-lifecycle grant. An authorized owner must independently land that
grant on develop before branch synchronization and revalidation; this worker
must not do either GitHub mutation. Provision PostgreSQL 17/18 and prove the
remaining acceptance legs before integration. Integration-scope is a CI
aggregation, not a locally executed green check.

Progress: checked 1, done 0 repairs, skipped 0 items, errors 1 blocking policy
failure (also reproduced by its test); Docker is an additional environment
blocker. Next is owner authorization and database availability, not scanner
suppression. Commit this evidence-only handoff locally; no closure claimed.
