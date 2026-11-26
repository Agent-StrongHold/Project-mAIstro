# Issue 1572 repair — dd25

## Frozen scope

Only issue #1572, branch `auto-1572`, starting head
`c9edf822e9eb2efba2f8189936261c84706d30dd`, assigned base
`2a11c1cc006a977ee76281307767319773d4fb62`.
Initial worktree is clean. Snapshot is the supplied dispatch-context.json;
no remote issue/PR enumeration will be performed.

Files eligible for repair: `quality/vulture-baseline.json` (explicit repair
exception only), canonical Goal modules/tests, their Run/Container integration,
Goal migration/tests and this validation report. No other grants/ledgers may
be changed. Existing implementation is preserved.

Ambiguity: integration-scope is an aggregate failure, not a scanner finding.
Proceed by reproducing the named vulture and execution-lifecycle gates against
the assigned base, and validating existing acceptance tests. No cosmetic
runtime repair or gate weakening is justified without reproduced evidence.

Initial result: exact head verified; repository instructions read; supplied
issue includes extended PostgreSQL installed-base upgrade acceptance, which
must not be inferred from SQLite or skipped tests.

Checkpoint 1: driver logs inspected: dependency sync, ruff and inventory pass;
focused tests report 55 passed / 16 skipped (not three-backend proof). Named
vulture command executed successfully: 1326 findings, none unclassified;
default provenance selected base `66f3cea9e989`, so explicit assigned-base
validation follows. No vulture ledger amendment is justified. Docker probe
with `DOCKER_HOST=unix:///var/run/docker.sock` fails: daemon unavailable.

ADR reconciliation: ADR-082226-5104 makes PostgreSQL the durable authority;
SQLite conformance is compatibility coverage, not proof of supported production
durability. ADR-091726-7c2a governs downstream interview commit orchestration,
which remains outside this store repair. Neither authorizes a second scheduler.

Checkpoint 2: against explicit assigned base, execution-lifecycles exits 1;
vulture and convergence-freeze pass. Focused Goal tests and migration suite
exit 0, with PostgreSQL skips still to be recorded below. Lifecycle checker
tests exit 1. First freeze invocation without required `--base` exited 2;
corrected invocation uses the verified assigned base. A guessed Hive source
glob was not found; skipped, use the repository's actual adapter path below.
No runtime or ledger changes have been made. The reproduced lifecycle blocker
requires trusted-base authorization, outside this worker's permitted changes.

Checkpoint 3: the explicit assigned base resolves correctly, but ratchet policy
uses merge-base `66f3cea9e98980f146a12cf3142d66e30986d276`. Both that merge-base
and assigned base contain **zero** `GoalStatus` occurrences in the authorization
file. Merely syncing the assigned base cannot supply the missing grant.
Goal-focused tests: 55 passed, 16 skipped. Migration suite: 38 passed, 127
skipped. Lifecycle checker suite: 28 passed, 1 failed at
`tests/test_check_execution_lifecycles.py:374`. Ruff lint and format independently
pass; inventory passes; Alembic reports the single head `062`.

Reachability inspection: Hive's adapter calls `create_container` at
`packages/hive-conductor/backend/adapters/maistro_core.py:195`; server does so
at `packages/maistro-server/src/maistro_server/main.py:344`. Container invokes
`wire_goal_store` at `packages/maistro-core/src/maistro/container.py:2362`.
This establishes source wiring, not a deployed PostgreSQL restart.

Important distinction: `integration-scope` aggregates PostgreSQL, object
storage, event, strike, Hive, wheel and Docker producer checks; the lifecycle
failure is independently reproduced, not proof of which specialized producer
caused the supplied aggregate failure. Exact-head aggregate readiness remains
unverified without those producer results.

## Executed validation and acceptance map

All Python commands used `uv run`. No tests were added or changed; inventory
notes need no delta. Only this report changed.

| Command (from assigned worktree) | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1326 reviewed findings, zero unclassified; also passes with explicit `RATCHET_BASE_REV=2a11c1cc006a977ee76281307767319773d4fb62` |
| `RATCHET_BASE_REV=2a11c1cc006a977ee76281307767319773d4fb62 uv run python scripts/check-execution-lifecycles.py` | FAIL, GoalStatus new vocabulary without already-landed grant, 19 to 20 identities |
| same environment, `uv run pytest tests/test_check_execution_lifecycles.py -q` | 28 passed, 1 failed (`:374`, shipped-ledger assertion) |
| `uv run python scripts/check-m1-convergence-freeze.py --base 2a11c1cc006a977ee76281307767319773d4fb62` | PASS, no unapproved architecture island |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q -rs` | 55 passed, 16 skipped |
| `uv run pytest packages/maistro-core/tests/runs -x -q` | 1187 passed, 271 skipped, 6 aiosqlite worker/event-loop-closed warnings; not repaired in this gate lane |
| `uv run pytest tests/migrations -x -q -rs` | 38 passed, 127 skipped |
| `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py -q -rs` | 2 passed (identity and snapshot provenance), 6 skipped (live upgrades) |
| `uv run alembic heads` | `062 (head)` |
| `uv run ruff check .`; `uv run ruff format --check .` | PASS; 3187 files formatted |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS |
| `git diff --check` | PASS |

Integration aggregation was also executed with `--event-name pull_request`
and scope computed by `ci_merge_group_scope.py --json` from
`git diff --no-renames --name-only 2a11c1cc006a977ee76281307767319773d4fb62...HEAD`.
All seven scope legs are required. The supplied snapshot contains no check-run
or status endpoint for the exact starting SHA. With no invented `--result`
arguments, `check-integration-scope.py` exits 1 listing all nine missing check
names. This is a local missing-evidence failure, **not** a reproduction of the
remote producer failure. No API refresh or GitHub mutation was performed.

Acceptance details:

- **Goal/GoalRevision round-trip on three backends:** memory and SQLite shared
  conformance passed (`test_goal_store_conformance.py:171`); PostgreSQL UNVERIFIED.
- **Append-only, stale revision refused, one concurrent winner:** shared
  conformance at `:197`, `:229`, `:278` passed on memory/SQLite; PostgreSQL
  UNVERIFIED. Terminal-final and explicit-only Goal outcome semantics pass.
- **Subgoal/Project lineage and recorded owner change:** shared tests at `:294`
  and `:333` pass on memory/SQLite; PostgreSQL UNVERIFIED.
- **Run binding and immutable historical revision:** `test_run_goal_binding.py`
  passes memory/SQLite admission and terminal transition preservation; SQLite
  restart read-back passes. Existing restart fixture advances the Goal before,
  not after, admission; a later Goal revision leaving the historical Run fixed
  remains explicitly UNVERIFIED by these tests. PostgreSQL binding UNVERIFIED.
- **Two-principal isolation and foreign equals missing:** shared seam tests at
  `test_goal_store_conformance.py:398` and `:472` pass on memory/SQLite, using
  `WorkspaceAuthorizer`; PostgreSQL UNVERIFIED.
- **Production composition:** Container construction and seam identity tests
  pass, and both shipped entry paths call it as cited above. PostgreSQL
  selection is tested with schema probes, not a running server here. Deployed
  Hive/server restart and durable read-back remain UNVERIFIED.
- **No second executor/lifecycle authority:** convergence-freeze passes. The
  distinct trusted lifecycle-authorization gate fails and cannot be waived by
  describing GoalStatus as DOMAIN in the candidate ledger.
- **Migration identity/ancestry:** identity and exact historical-file checks
  pass, single head 062. Actual populated c560d4c/4675101 upgrades, table/data
  preservation, planner constraints/indexes, fresh-install/downgrade/reapply,
  and durable bound-Run reopen on PG17 and PG18 remain UNVERIFIED here. Central
  allocation coordination and complete older quota-door history audit remain
  UNVERIFIED. Prior-job PG18 success is historical evidence, not a run here.

## Handoff

**BLOCKED.** The only reproduced policy failure requires an independently
landed GoalStatus authorization in the trusted base, then a permitted branch
sync and revalidation. Do not disguise/remove GoalStatus to evade discovery,
change the lifecycle ledger/grants here, or amend a passing Vulture ledger.
Once infrastructure is available, rerun live PG17/18 acceptance and obtain
exact-head specialized CI evidence before claiming integration readiness.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: trusted-base
GoalStatus authorization and live PostgreSQL/exact-head CI validation}`.
Diagnostic logs are `/tmp/1572-dd25-*.log`; this committed report preserves the
outcomes if those temporary logs expire. Work is evidence-only, not an
implementation repair or integration approval.
