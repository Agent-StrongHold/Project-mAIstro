---
inventory-delta:
  packages/maistro-core/tests: +60
---

# 1572-canonical-goal-store

Issue #1572 ships the canonical Goal store (`maistro.goals`): `Goal`,
append-only `GoalRevision` chain, Subgoal lineage, recorded lifecycle and
ownership transitions, one protocol over in-memory/SQLite/PostgreSQL
backends, Workspace-seam authorization, and immutable Run-admission binding.
Fifty-four node IDs arrived with the first implementation and six more with
the coverage repair below — sixty in all, in
`packages/maistro-core/tests/goals/` except two gained legs of an existing
suite, described last.

`test_goal_store_conformance.py` (+20, parametrized ×3) is one suite over all
three backends — the in-memory reference and the SQLite and PostgreSQL
durable twins — because "the durable stores behave like the reference" is a
comparison only when the same bodies run over all three. It holds every
backend to the issue's acceptance pairs: Goal/revision/transition round-trip
through a reopen; append-only revisions with a stale CAS refused and a
concurrent append leaving exactly one winner; lifecycle CAS with every
transition out of every terminal state refused; Subgoal lineage preserving
parent Goal and Project (and refusing a parent in another Workspace or
Project); agent reassignment as a recorded, attributed, both-sides-carrying
transition with the no-op refused; and the authorization seam driven over
each backend so two principals in two Workspaces cannot read or mutate each
other's Goals and a foreign Goal raises byte-identical
`GoalNotVisible` to a missing one. The PostgreSQL leg needs a migrated
server (`MAISTRO_TEST_PG_DSN`) and skips loudly tracked-by
`MAISTRO_REQUIRE_PG_LEGS` otherwise — it was run green against a PG18
database at `alembic upgrade head` before this note was written, and it is
the leg that caught the one real bug the suite now pins: a transition does
not move `current_revision`, so the PostgreSQL CAS carries a
`status = 'active'` arm as well (the state half of "compare-and-set on
revision and state"), without which the second of two concurrent transitions
silently overwrote the first.

`test_run_goal_binding.py` (+11) proves the spine half: `admit_direct_work`
binds `goal_id`/`goal_revision` over all three Run stores — in-memory,
SQLite, and PostgreSQL (the durable JSONB payload driven directly, so "PG
rides the same payload" is a tested claim, not an architecture argument) —
the binding survives storage, every subsequent transition to terminal leaves
it untouched (a historical Run keeps the revision it used), unbound admission
stays unbound, a half binding is refused at the model, and a terminal Run
never moves its Goal's state — the Goal moves only through the one explicit
writer, with no transition record appearing on the Run's account.

`test_goal_wiring.py` (+6) proves composition rather than library:
`create_container` — the one composition both shipped products call — exposes
`goal_store` and a `goal_reader` that wraps the container's own stores;
`wire_goal_store` selects SQLite over a SQLite pool, PostgreSQL over a
migrated pool, refuses an *unmigrated* PostgreSQL pool with a loud in-memory
fallback instead of a store querying tables that do not exist, and falls
back to memory with a warning naming #1572 when no database exists; and a
Goal created through the container's seam is readable by its principal and
`GoalNotVisible` to everyone else.

`test_goal_restart_readback.py` (+1) is the closure leg: one SQLite file
carrying the Goal tables and the canonical Runs together — the supported
durable composition at this tier — written, every connection closed, and
read back through fresh stores with the same Goal, the same two revisions,
both recorded mutations (agent reassign and status move, each with both
sides), and the Run still carrying the goal revision it was admitted
against rather than the Goal's current one.

`test_goal_model.py` (+9) pins the record guards the stores can only be as
strict as: frozen revisions, pointer numbering from 1, no self-parenting,
required identity fields, the terminal-set and legality table (only `active`
has outgoing moves; no state moves to itself), and transition records that
must carry both sides of their kind.

Finally, the existing
`workspaces/test_sqlite_alembic_schema_parity.py` (+0 node IDs) now walks
the three Goal tables too: SQLite's own DDL and migration 059 are held to
one dialect-neutral spec (column sets, nullability, integer/timestamptz/doc
types, keys, the self-referential lineage cascade, and the project index),
so the two descriptions of the same tables cannot drift the way the scope
tables once did (#1135).

## Repair-round validation evidence (2026-10-04, head d635a9c90)

Re-proven on a fresh PG18 container (`pgvector/pgvector:pg18`) after
`alembic upgrade head` (000→054) with `MAISTRO_REQUIRE_PG_LEGS=1` and
`MAISTRO_TEST_PG_DSN` set — no leg skipped:

- `pytest packages/maistro-core/tests/goals
  packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py`
  → 56 passed (all three conformance legs, PG Run-binding leg, PG wiring leg,
  restart read-back, parity).
- `pytest packages/maistro-core/tests/runs` → 1362 passed, 3 skipped
  (Run-spine regression over the binding change).
- CI-exact gates: `ruff check .`, `ruff format --check .`,
  `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (1342 reviewed = 1342 findings, unclassified
  0 — no ledger amendment owed), `check-m1-convergence-freeze.py --base
  928993d`, `check-reachability.py`, `check-promotion-surface.py`,
  `check-suite-inventory.py`, `check-radon-baseline.py`,
  `check-durable-table-inventory.py` — all exit 0. `mypy
  packages/maistro-core/src`: only the 5 pre-existing `maistro_bootstrap`
  import-not-found errors in untouched `maistro/cli/` files.
- Still red by design of the two-merge rule, unchanged from the disclosure
  in commit 9ce54854f: `check-execution-lifecycles.py` refuses
  `maistro.goals.model::GoalStatus` until the DOMAIN classification grant
  lands in `quality/execution-lifecycles.json` via a separate earlier PR
  (the gate reads authorizations from the merge base `91996e192`, so no edit
  on this branch can satisfy it). This ledger stays untouched here.

## Repair round 2 (2026-10-04, after merging develop `35f2e0158`)

The develop merge collided with this branch in three places, all fixed here
and all proven against real PostgreSQL servers (pgvector pg17 and pg18):

- **Migration number collision (was breaking every alembic step in CI):**
  develop landed its own `053_learning_lifecycle_columns` while this branch
  carried `053_canonical_goals` — two revision 053s, two heads, so
  `alembic upgrade head` failed outright. Renumbered to `054_canonical_goals`
  with `down_revision = "053"`, following the re-parent convention that
  develop's own 053 records. The upgrade was also made adoption-tolerant
  (`CREATE TABLE IF NOT EXISTS`, the 046/047 style) because
  `tests/migrations/test_migration_chain.py`'s stamp-back-and-re-upgrade
  walk re-runs the revision over its own schema. Every textual `053`
  reference in `maistro.goals`, the tests and this note moved to `054`.
- **`EXPECTED_TABLES` in the chain test** now names the three Goal tables,
  so `test_upgrade_head_creates_every_expected_table` asserts them on the
  live catalog instead of failing on the extras.
- **`PgRunStore.prepare_run` lost the Goal-binding parameters in the
  merge** (develop's #1845 split of `create_run`): the kwargs referenced
  names that no longer existed in `prepare_run`'s scope — ruff F821 at
  rest, a `NameError` on every PostgreSQL admission at runtime. The
  parameters moved onto `prepare_run` with `create_run` passing them
  through.

Coverage repair: the new `goals/pg_store.py` was measured at 25% by the
diff-coverage producers — `coverage (no services)` runs the whole core suite
but its PostgreSQL legs skip, and `coverage (PostgreSQL)`'s suite list did
not include `tests/goals`, so the durable store's arcs were measured
nowhere. The suite joined the `coverage (PostgreSQL)` producer (the
workflow's own rule: a new PostgreSQL store means an edit there, every
time) and gained a step in ci.yml's `postgres` matrix so both supported
majors carry the verdict. Two seam tests (`+6` node IDs) close the
authorization paths the isolation tests could not reach — an authorized
member driving append/transition/reassign and both chain reads through
`ScopedGoalStore`, and a substrate `LookupError` converting to the one
`GoalNotVisible` — taking `goals/authorization.py` from 87% to covered and
every changed goals file over the 90% line / 80% branch per-file floors.

Re-proven after the fixes, both majors: migration chain apply/downgrade/
re-apply (`tests/migrations`), persistence + `test_container_postgres.py`
(745 passed on pg17), `tests/goals` + schema parity + workspaces with
`MAISTRO_REQUIRE_PG_LEGS=1` (60 + 56 + 330 on pg17; 397 combined on pg18),
canvas supported path (7 passed), full `packages/maistro-core/tests`
(12305 passed), server + canvas + bootstrap suites (1194 passed),
wheel-imports from built wheels, and the gate battery (`ruff check`,
`ruff format --check`, vulture ledger with CI's exact scan arguments,
radon, durable-table inventory, M1 convergence freeze, enumerations,
doc links, workspace retirement, route permissions, principal identity,
backlog, release consistency, reachability, promotion surface,
reachability dispositions, suite inventory).

Still structurally red on this branch, unchanged in kind from the first
round: `check-execution-lifecycles.py` (part of the `quality-gate` job)
refuses `maistro.goals.model::GoalStatus` because the merge-base ledger
`35f2e0158` carries no authorization for the new vocabulary and the gate
reads authorizations from the base — "a candidate may not introduce a
lifecycle and approve it in the same change", its own docstring. The
sanctioned path is a separate grant PR classifying `GoalStatus` (DOMAIN:
desired-state vocabulary, not execution state; the M1 convergence freeze
passes), merged before this branch. Until that lands and develop is
re-merged, the quality-gate job fails on exactly this one finding.
`quality/execution-lifecycles.json` is deliberately untouched here.

## Repair round 3 (2026-10-05, head 69d6411d4, independent re-verification)

Every round-2 claim re-executed from scratch on fresh databases, node ID for
node ID, with no edits to the round-2 tree:

- Fresh pg18 **and** pg17 containers, empty databases: `alembic upgrade head`
  walks 000→054 on both; `tests/migrations` chain tests green; single head 054.
- `tests/goals` with `MAISTRO_REQUIRE_PG_LEGS=1`: **60 passed, 0 skipped on
  both majors**; schema parity 2 passed on both.
- The `prepare_run` Goal-binding fix driven from the consumer side: runs
  admission + PG admission atomicity/coordinator suites green with legs
  required (25 + 14 passed).
- Full `packages/maistro-core/tests` (no services): 12309 passed, 802
  skipped, 1 xfailed.
- Coverage battery reproduced locally with PG legs (core suite + the root
  `scripts` producer over `tests/`), then the gate itself:
  `check-diff-coverage.py --base 35f2e0158` — **ok**, every measured changed
  file at or above the 90%-line / 80%-branch floors.
- Gate battery: `ruff check` / `ruff format --check`, vulture ledger with
  CI's exact scan arguments (1339 = 1339), durable-table inventory (92
  tables), enumerations provenance, M1 convergence freeze
  (`--base 35f2e0158`), suite inventory (13112 node IDs, matching).
- The one red remains exactly as documented above: the shipped-ledger test
  `tests/test_check_execution_lifecycles.py::
  test_the_shipped_ledger_matches_the_shipped_code` fails on the same single
  `GoalStatus` finding, and `quality/` is untouched.

## Repair round 4 (2026-10-05, develop syncs to `cd561822` then `30144ad0`)

Two develop syncs in one round, each colliding with this branch on the same
chain tip the store's migration sits at:

- **Second and third migration collisions (the integration-scope breaker):**
  develop's #1892 claimed `054` off the `053` head this store had re-parented
  onto, and the next sync claimed `055` again (#119's
  `054_learning_applicability_epistemics` re-parented #1892 to
  `055_task_admission_generations`). The store's migration re-parents twice in
  step — now `056_canonical_goals` (`down_revision = "055"`), per the chain's
  collision convention — and every textual reference in `maistro.goals`, the
  parity/chain tests and this note moved with it. Proven on fresh empty
  pgvector pg18 **and** pg17: `alembic upgrade head` walks 000→056, stamps
  `056`, and leaves the three Goal tables; single linear head `056`.
- **Develop's task-admission downgrade test hardcoded the chain tip** (`assert
  _stamped_version() == "055"`): on any integrated tree the tip is the branch's
  revision, so the refusal test failed for the wrong reason. It now captures
  the head it upgraded to and asserts the stamp did not move — the same
  assertion at the same strength, tip-independent. 14/14 pass on pg18.
- **Pyright ratchet, branch debt paid:** the 8 findings in `goals/pg_store.py`
  (PoolConnectionProxy vs Connection on the three connection-taking helpers,
  and the `fetchval -> int` assignment) are fixed with the repo's established
  shapes (`asyncpg.pool.PoolConnectionProxy` like `pg_learnings.py`; the
  store's existing `int(x or 0)` spelling for the typed-`| None` aggregate).
  Measured with pyright 1.1.414 on identical inputs: develop tip `30144ad0` =
  35 errors, this branch = 27, **branch-only = 0** — the residual over
  `PYRIGHT_BASELINE: 21` is develop's own debt under the current analyzer
  version, not this change's. `mypy --strict` clean on all packages.
- **Vulture ledger:** re-run with CI's exact arguments against the new base —
  1338 = 1338, unclassified 0, exit 0. `quality/vulture-baseline.json` needed
  no amendment; the syncs' net identity count already matched.
- **Integration-scope required evidence, reproduced locally:** postgres
  (pg17+pg18) as above; goals conformance **60/60 with
  `MAISTRO_REQUIRE_PG_LEGS=1` on both majors**; schema parity 2/2 on both;
  durable-events 382 passed, strike-ladder + elevation 46 passed (pg18 legs);
  wheel-imports re-run with every package wheel built (`--python 3.12`) —
  "All wheels import from a clean venv", exit 0, bare tier 61 checks including
  `maistro.goals`; hive-conductor-e2e run from this tree via
  `docker compose -f docker-compose.test.yml --profile test up --build
  --exit-code-from api-tests` — api-tests exit 0 (10 passed, 13 skipped), the
  live production composition booting with the Goal store wired. Not locally
  reproduced: docker-build's full four-image matrix (the hive image built
  from this tree as part of the e2e), the Playwright UI leg, and MinIO
  object-storage (no archive/object-storage path in this branch's diff).
- **Still red, unchanged and unfixable from a branch:** the execution-lifecycle
  ledger. The base (`30144ad0`) classifies 19 vocabularies, carries no
  `GoalStatus` authorization, and the gate reads `quality/
  ratchet-authorizations.json` from that base — the sanctioned DOMAIN grant
  must land on develop first (two-merge rule), then this branch re-merges.
  The candidate ledger stays untouched, per rounds 1–3.

## Round 5 — develop sync (658a8f78c + b672b799a), migration collision 4, wheel-imports fix

- **Develop sync completed in two merges.** The prior attempt died mid-merge
  (GH API rate limit) leaving an in-flight merge of `658a8f78c` with two
  conflicted migration tests; resolved and committed, then `b672b799a`
  merged cleanly on top. No test counts changed (`check-suite-inventory.py
  --suite packages/maistro-core/tests` ok, 13,786 identities).
- **Fourth migration collision resolved in develop's favor.** Develop's
  `043_invocation_quota_door` (#1196/#718) landed on `055` — the same
  parent this store had claimed as `056`. Per the chain's standing
  convention (later-integrated revision re-parents onto the landed tip),
  `056_canonical_goals` now continues the quota door
  (`down_revision = "043_invocation_quota_door"`); the single linear head
  stays `056` (`ScriptDirectory.get_heads() == ["056"]`). The conflicted
  test comment blocks record the merged history; the task-admission
  downgrade guard keeps afdad68be's tip-independent stamp assertion.
- **Live-PG18 (native 18.6) verification of the integrated chain:** all 47
  tests in `test_capability_invocation_effect_index_migration.py`,
  `test_task_admission_generation_upgrade.py`, `test_single_migration_head.py`,
  `test_migration_chain.py`, `test_memory_entries_embedding_type.py`
  passed (27 had been skip-only in every earlier round); a fresh database
  walks `054 -> 055 -> 043_invocation_quota_door -> 056` cleanly.
- **Goals suite on the merged tree:** 60/60 with `MAISTRO_REQUIRE_PG_LEGS=1`
  against the migrated PG18 database (0 skips); quota + workspaces parity
  242 passed; durable-events 387 passed (pg18 legs); strike-ladder
  conformance 40 passed.
- **wheel-imports producer failure root-caused and fixed.** PyPI now hosts
  same-version (0.9.0) `maistro-*` snapshots; with the version tie between
  the local wheel and the stale published artifact, uv's index-vs-
  find-links choice flipped between runs (base tree passed, candidate tree
  failed in the same environment minutes apart; the losing venv installed
  an 11,681-byte `maistro/tools/git/server.py` lacking `git_remote_tip`).
  `scripts/verify-wheel-imports.py` now writes a direct-reference
  constraint per built wheel so sibling `maistro-*` deps resolve from
  `dist/` deterministically; third-party deps still come from the index.
  Candidate `dist/` passes 3/3 consecutive full runs; the same run against
  a base-built `dist/` still refuses the new `maistro.goals` bare-surface
  entry, which is the gate working as designed.
- **Deterministic aggregator steps:** merge-group scope resolution (all 7
  legs in scope, 9 required checks), `node --test tests/ci/
  integration-scope.test.cjs` 12/12, `check-required-checks.py` ok.
  Ratchet battery green: vulture ledger 1342 = 1342 (unclassified 0), radon,
  xenon 138 ≤ 145, reachability, wiring-reads, agent-store-writes, contract
  markers, convergence matrix, reachability dispositions, route-permissions,
  durable-table inventory (98 tables), promotion surface, M1 convergence
  freeze (`--base b672b799a`), backlog consistency, release consistency,
  doc links, interrogate (all 12 floors), `mypy --strict` (818 files),
  ruff check + format, acceptance-state ratchet + mandate + chain mandate
  against `b672b799a` (every declared criterion proven).
- **Pyright:** 27 errors vs `PYRIGHT_BASELINE: 21` — unchanged from round 4's
  analysis: base measures 35 under the current analyzer, this branch is −8
  with 0 new findings; the residual 6 are develop's own debt in files this
  change never touches. The round-3 `goals/pg_store.py` findings no longer
  reproduce (0 pyright diagnostics in `maistro/goals/`).
- **Still red, still structural:** the execution-lifecycle ledger against
  the new base (`b672b799a`, 19 classified, no `GoalStatus` authorization;
  `tests/test_check_execution_lifecycles.py::
  test_the_shipped_ledger_matches_the_shipped_code` mirrors the gate). The
  DOMAIN grant must land on develop first (two-merge rule); the candidate
  ledger stays untouched, per rounds 1–4.
- **Not re-runnable this round:** docker-build matrix, Playwright UI leg,
  MinIO object-storage, and the hive e2e compose bring-up (Docker Desktop
  engine down in this environment); none of this round's diffs touch those
  paths, and round 4 recorded them green from this branch's content.

## Round 6 — develop sync (7334621bf) and the migration-identity repair (2026-10-06 clarification)

- **Develop sync completed and committed.** `origin/develop` at `7334621bf`
  merged in-branch as `6cb5c729c`; worktree clean, merge-base == develop
  base. The sync brought the merged identities this round's repair is about:
  `056_user_model_facts` (#1951, merge `c560d4c`) and
  `057_run_store_planner_stability` (#1914, merge `4675101`).
- **The earlier merge resolution kept this branch's renumber** — Goals at
  `056`, user-model moved to `057`, planner to `058` — exactly the
  installed-base hazard the clarification added to the issue: a database
  migrated by develop to `056` or `057` would treat the Goal DDL as already
  applied and skip it. Fixed per the clarification:
  - develop's `056_user_model_facts.py` and `057_run_store_planner_stability.py`
    restored byte-for-byte (verified identical to the merge commits and to
    `origin/develop`'s tip);
  - the Goal DDL re-homed as `058_canonical_goals` (`revision = "058"`,
    `down_revision = "057"`) — an unused id appended after the integrated
    develop head, one linear head;
  - every textual reference moved with it (`maistro.goals` docstrings, the
    planner/status-lockstep/effect-index/chain tests, the SQLite parity
    note), and `043_invocation_quota_door`'s chain narrative rewritten to
    the restored identities.
- **New installed-base suite** `tests/migrations/test_goal_installed_base_upgrade.py`
  (+6 node IDs, own note `1572-goal-installed-base-upgrade.md`): graph-shape
  identity, byte-identity against the real merge commits, the named
  regression (user-model at `056`, no Goal tables), true snapshot-tree
  upgrades from `c560d4c` and `4675101` with no stamp edit, and the durable
  Goal composition driven on the upgraded schema.

## Round 7 — develop sync (b6c50ef99) migration collision and shared-DB repair

- Develop's accepted `058_learning_validation_provenance` claimed the id this
  branch had used for Goals. The Goal migration is therefore now
  `059_canonical_goals` (`down_revision = "058"`), preserving develop's
  installed 058 identity and retaining one linear head. The installed-base
  graph test asserts both edges and filenames.
- The installed-base fixture now restores the shared `tests/migrations`
  PostgreSQL database to `alembic upgrade head` after each isolated
  downgrade/drop walk. This prevents later migration modules in quality's
  single `pytest tests/migrations` process from inheriting an empty database.

## Round 8 — current trusted-base ratchet evidence (2026-10-06)

`quality/execution-lifecycles.json` **does** carry the candidate's
`maistro.goals.model::GoalStatus` `DOMAIN` classification. Earlier wording
that the candidate ledger was untouched described the pre-classification
rounds and is not current-state evidence. It cannot authorize this change:
`uv run python scripts/check-execution-lifecycles.py` at
`be45a17d1a77e10acd20862128f542d855f1dcc7` resolves trusted base
`11376c7bef4ea7d17195b90bea8ca9a64a769bb1`, finds 19 classified lifecycles
there and 20 in the candidate, and fails because that base contains no
already-landed authorization for `GoalStatus`. The mirrored shipped-ledger
unit test fails for the same reason. The vulture ledger is independently
clean with CI's exact scan arguments (1332 reviewed identities and findings).
The required repair remains a separately merged authorization on develop,
followed by a branch sync; no candidate-only ledger edit can satisfy the
two-merge rule.

## Round 9 — focused validation at `f30f31210` (2026-10-06)

The CI-repair instruction named the vulture exact-debt ledger. Re-running its
CI scan found **1332 reviewed identities, 1332 findings, 0 unclassified and 0
never-allowlisted**, so there is no vulture ledger amendment to make. The
remaining failure is instead independently reproduced by both
`check-execution-lifecycles.py` and its shipped-ledger unit test: trusted base
`11376c7bef4e` has 19 classifications while this candidate has 20, and lacks
the already-landed authorization for
`maistro.goals.model::GoalStatus`. `origin/develop` at `626683154` still has
no GoalStatus authorization, so the mandated separate-grant-then-sync repair
is not available in this worktree. The GoalStatus entry already present in the
candidate's `quality/execution-lifecycles.json` cannot approve itself.

Focused non-PostgreSQL behavior passed: the Goal suite plus SQLite schema
parity was **46 passed, 16 skipped**, and the installed-base module plus
migration-chain static checks was **2 passed, 17 skipped**. Ruff, the core
suite inventory, durable-table inventory (100 tables), and the M1 convergence
freeze also passed. PostgreSQL acceptance legs remain unverified in this
round: `DOCKER_HOST=unix:///var/run/docker.sock docker info` could not connect
to a daemon, and neither PostgreSQL test URL was configured. The lifecycle
ratchet is therefore the release blocker; no source or vulture debt was
changed to disguise it.

## Round 10 — current-base verification (2026-10-06, `69be819b5`)

The issue's relevant acceptance tests were re-run against the current merged
base `a8258ee24`: the focused Goal/Run/SQLite-parity selection passed **46
passed, 16 skipped**; installed-base identity and migration-chain static
coverage passed **2 passed, 17 skipped**; M1 convergence freeze,
durable-table inventory (100 tables), the core suite inventory (14,369 node
IDs), and the CI-exact vulture scan all passed (1,332 reviewed identities =
1,332 findings, zero unclassified).

The required PostgreSQL acceptance legs remain **unverified** in this local
round: the configured Docker socket cannot reach a daemon, so no PostgreSQL
server could be started. The sole release blocker is independently
reproduced: both `check-execution-lifecycles.py` and
`test_the_shipped_ledger_matches_the_shipped_code` fail because the trusted
base has 19 classifications and no already-landed authorization for the
candidate's `maistro.goals.model::GoalStatus` entry (20 discovered
lifecycles). The branch cannot self-authorize that new vocabulary; the
separate grant must merge to develop before this branch can sync and pass the
two-merge ratchet.

## Round 11 — PostgreSQL acceptance executed on both supported majors (2026-10-06, `9e223f0708`)

Rounds 9–10 recorded the durable legs as unverified because no Docker daemon
was reachable. This round reached the rootless daemon
(`DOCKER_HOST=unix:///run/user/1000/docker.sock`) and ran both `pgvector`
majors as containers (pg17 on 127.0.0.1:15432, pg18 on 15433), driving the
CI-exact step sequences:

- **pg17** — `tests/migrations` against an unmigrated database: **153 passed**
  (previously the shared-database teardown leak made this exact CI step fail);
  then `alembic upgrade head` → `downgrade base` → `upgrade head`
  (the log shows `058 -> 059` on both walks); then persistence +
  `test_container_postgres.py` **824 passed, 84 skipped**; then
  `tests/workspaces` **328 passed, 2 skipped** and `tests/goals`
  **60 passed, 0 skipped** under `MAISTRO_REQUIRE_PG_LEGS=1` — the
  PostgreSQL conformance leg did not skip.
- **pg18** — `tests/migrations` **153 passed**; after `alembic upgrade head`,
  goals + workspaces + persistence + container-postgres **1212 passed,
  86 skipped**.
- The installed-base walks ran on both majors: databases built by the actual
  develop snapshots (`c560d4c` at 056, `4675101` at 057) forward-upgrade to
  `059` with no stamp edit, keep the planner indexes/CHECK and the pre-existing
  user-model/Run rows, serve the durable Goal composition, and read back the
  bound Run provenance after a full close/reopen.
- Gates re-run at this head with CI arguments: vulture **1332 = 1332,
  unclassified 0** (no amendment needed); M1 convergence freeze ok;
  durable-table inventory **100 tables**; canonical mypy line **842 files,
  no issues**; ruff check/format green (driver checks).
- The one red gate is unchanged and structural:
  `check-execution-lifecycles.py` and its mirrored shipped-ledger unit test
  (**28 passed, 1 failed** — the mirror) still fail on
  `maistro.goals.model::GoalStatus` because trusted base `d39a2e4ce330` has
  19 classifications and no already-landed authorization. Everything
  repairable in this worktree is repaired; the separate grant on develop
  followed by a branch sync remains the release step.

## Round 12 — every required integration-scope check executed at head `45df99115` (2026-10-06)

The merge-queue evaluation had named `integration-scope: failure`. Its
required-check set for this diff is all nine specialized producers
(`scripts/check-integration-scope.py` over the merge-base diff:
docker-build, durable-events, hive-conductor-e2e, hive-conductor-e2e-ui,
object storage (MinIO), postgres (pg17), postgres (pg18), strike-ladder,
wheel-imports). All nine were re-executed locally against this exact head;
the rootless daemon (`DOCKER_HOST=unix:///run/user/1000/docker.sock`) served
every container:

- **quality.yml coverage (PostgreSQL) step 1, CI-exact** — full
  `pytest tests/migrations` under coverage against an unmigrated pg17
  database: **153 passed** (the shared-database teardown leak that made this
  step fail with 5 failed/40 errors is fixed by the round-7 restore; the
  installed-base module re-stamps `upgrade head` after each walk).
- **quality.yml coverage (PostgreSQL) step 2, CI-exact** — `alembic upgrade
  head` (converged to `059`, 70 tables) then the step's full 13-suite list
  (persistence, container-postgres, events, runs, graph, projects,
  workspaces, goals, scheduling, idempotency purge, elevation durable,
  memory/user_model, quota): **5634 passed, 92 skipped**.
- **postgres (pg17), CI-exact ci.yml walk** on a fresh database — chain
  apply on empty → `upgrade head` → `downgrade base` → `upgrade head` →
  persistence **809 passed** → container-postgres **15 passed** → workspaces
  **328 passed, 2 skipped** → goals **60 passed, 0 skipped** → canvas
  supported path **7 passed** (all with `MAISTRO_REQUIRE_PG_LEGS=1`).
- **postgres (pg18)** — the same walk on pgvector pg18: persistence **809**,
  container-postgres **15**, workspaces **328, 2 skipped**, goals
  **60, 0 skipped**, canvas **7** — all green.
- **wheel-imports** — every package wheel built from this tree, then
  `verify-wheel-imports.py --dist dist/ --python 3.12`: all wheels import
  from a clean venv, exit 0 (bare tier includes `maistro.goals`).
- **hive-conductor-e2e-ui** — CI-exact compose bring-up of the live hive
  service from this tree (host port overridden to 18101 only because the
  dev stack holds 8101; in-container networking untouched): Playwright UI
  suite **121 passed, exit 0**.
- **hive-conductor-e2e** — the api-tests profile against the same live
  composition: **exit 0** (10 passed, 13 skipped, matching round 4).
- **durable-events** — CI-exact against pg17 with legs required: events
  **382 passed**, `test_event_schema_agreement.py` **5 passed**.
- **strike-ladder** — CI-exact: **40 passed** with the PostgreSQL leg
  required.
- **object storage (MinIO)** — server built from the pinned pseudo-version
  through the Go module proxy exactly as the workflow does
  (`v0.0.0-20250422221226-0d7408fc9969`), health-checked on 127.0.0.1:9000;
  archive conformance **128 passed** with the workflow's S3 env.
- **docker-build** — `maistro-engine:test` built from this tree; the #406
  shipped-image examples-namespace check passed; the empty-PostgreSQL-18
  volume boot smoke passed end to end: engine boots, applies the chain —
  **stamped revision `059`** — `/health/live` and `/health/ready` answer ok,
  and after tearing down both containers the restarted engine serves ready
  from the migrated volume. (The engine-research and rsi-runner image builds
  were not re-run locally; no Dockerfile changed in this diff, and their
  package content is import-proven by the wheel leg above.)
- Ratchet state at this head: vulture ledger with CI's exact scan arguments
  **1332 reviewed identities = 1332 findings, 0 unclassified** (no amendment
  owed); durable-table inventory **ok: 100 tables**; M1 convergence freeze
  vs base `bc40b6cda` ok; ruff check + format green; suite inventory 16
  suites match.
- Still red, and still the only red: `check-execution-lifecycles.py` and
  its mirrored shipped-ledger unit test (**28 passed, 1 failed**) on the
  single `maistro.goals.model::GoalStatus` finding. Trusted base `1e640df17`
  classifies 19 vocabularies and carries no `GoalStatus` authorization, and
  `origin/develop` at its current tip `bc40b6cda` carries none either — so
  the mandated separate-grant-then-sync repair is still not available in
  this worktree. The candidate's `quality/execution-lifecycles.json`
  classification cannot approve itself, and no edit on this branch can
  satisfy `load_authorizations(RATCHET, base=...)`. The release step remains:
  merge the GoalStatus DOMAIN grant on develop, then sync this branch.

## Round 13 — head `4b65be6d6bc3` re-verified end to end; live CI failures root-caused to the one structural red (2026-10-06)

This round closed the two evidence gaps the previous dispatch recorded and
root-caused every red job in the latest merge-queue evaluation to the single
known structural finding. No production file changed; the only edit is this
note.

- **PostgreSQL legs re-executed at this exact head.** The prior round's
  "Docker daemon unreachable" premise no longer held: the rootless daemon
  (`unix:///run/user/1000/docker.sock`) served a fresh `pgvector/pgvector:pg17`
  container on 127.0.0.1:15432 and the full ci.yml `postgres (pg17)` walk ran
  CI-exact against it: migration chain **13 passed**; `alembic upgrade head`
  → `downgrade base` → `upgrade head` (stamped **059**); persistence
  **809 passed, 84 skipped**; container-postgres **15 passed**; workspaces
  **328 passed, 2 skipped**; goals **60 passed, 0 skipped** with
  `MAISTRO_REQUIRE_PG_LEGS=1`; canvas supported path **7 passed**. Without a
  DSN the goals suite still behaves correctly (45 passed, 15 loudly-skipped
  PG legs). Code-identity with the round-12 head is confirmed by an empty
  `git diff 45df99115..4b65be6d` over `packages/maistro-core/src/maistro/goals`,
  `tests/goals`, `container.py`, `alembic/`, `tests/migrations`, and
  `tests/workspaces` — and is now superseded by execution at this head.
- **Live CI state at this SHA, read via the checks API.** All nine
  integration-scope required producers succeeded at `4b65be6d` (docker-build,
  durable-events, hive-conductor-e2e, hive-conductor-e2e-ui, object storage
  (MinIO), postgres pg17, postgres pg18, strike-ladder, wheel-imports), as did
  `integration-scope` itself and `exact-debt-ledger`. Three jobs failed —
  Quality gate (job 112396757644), Coverage gate (112402090487) and test
  (112396758942) — and their logs show **one shared root cause**:
  `check-execution-lifecycles.py` exit 1 on
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from
  the trusted base and has no already-landed authorization` (baseline
  bc40b6cda, 19 classified → 20 discovered; candidate 417f74b67c54 in the
  queue merge). The test and coverage jobs failed on nothing else — the test
  job's sole failure was the mirrored
  `test_the_shipped_ledger_matches_the_shipped_code` (1 failed, 4621 passed),
  re-reproduced locally (1 failed, 28 passed in the module).
- **origin/develop re-fetched and still grant-less.** The branch is "behind 1"
  only by `3f8ccbe9d` (unrelated M9-H2 SDK-harness WIP, #2016); its
  `quality/ratchet-authorizations.json` contains no `GoalStatus` entry under
  `execution-lifecycles` (grep count 0). A develop sync therefore cannot clear
  the gate by itself — the dispatch's "if it was a develop sync conflict"
  remedy does not apply; this is not a sync conflict.
- **Lane's vulture-ledger repair instruction evaluated; not applicable.** The
  vulture gate was re-run with CI's exact arguments
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`):
  **1332 reviewed identities = 1332 findings, unclassified 0** — nothing dead
  to fix, no amendment owed, and CI's `exact-debt-ledger` job agrees. The red
  ledger is `execution-lifecycles`, whose authorization file is read from the
  base by design; amending it on this branch would be the self-authorization
  the two-merge rule exists to prevent, so `quality/` is untouched here.
- **Ratchets that can pass at this head, re-run and green:** vulture (above),
  durable-table inventory (**ok: 100 tables**, canonical retention declared),
  M1 convergence freeze vs base `bc40b6cda` (no unapproved architecture
  island — the issue's no-second-executor criterion), ruff check/format, and
  suite inventory (14,564 unique node IDs across one suite).

The release step is unchanged and precise: land the GoalStatus DOMAIN grant on
develop (`quality/ratchet-authorizations.json` → `execution-lifecycles` →
`maistro.goals.model::GoalStatus`, owner/issue/reason), then merge
origin/develop into this branch so `load_authorizations` reads it from the new
base. The classification is already banked in this branch's
`quality/execution-lifecycles.json`; after the grant lands and the branch
syncs, the gate, its mirrored test, and the three red jobs clear without any
further code change.

## Round 14 — head `da516dd9daed` (develop sync to `df00785bb41b`) re-verified; the GoalStatus two-merge red persists and remains the sole blocker (2026-10-06)

Independent verification at the merged head. No production file changed; the
only edit is this note.

- **The lifecycle ratchet still fails, now against base `df00785bb41b`.**
  CI-exact `uv run python scripts/check-execution-lifecycles.py`: **EXIT 1**
  (`19 classified -> 20 discovered`; `maistro.goals.model::GoalStatus: NEW
  work-state vocabulary is absent from the trusted base and has no
  already-landed authorization`). The mirrored
  `tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code`
  failed (1 failed, 28 passed). The `quality.yml` execution-lifecycles step
  (line 1470) and therefore the `integration-scope` aggregator stay red on
  this PR until the grant lands.
- **The sync did not and could not clear it.** `git diff
  df00785bb41b..da516dd9daed -- quality/ratchet-authorizations.json` is
  empty and the base file carries no `GoalStatus` entry (grep count 0) —
  develop has not yet merged the grant, so the two-merge sequence is still
  unsatisfied and no edit on this branch can satisfy
  `load_authorizations(RATCHET, base=...)`. Release step unchanged: land the
  GoalStatus DOMAIN grant on develop, then sync this branch.
- **Everything runnable without PostgreSQL re-ran green at this head:**
  `ruff check .` (all checks passed) and `ruff format --check .` (3104
  files); the lane's pytest argv (`tests/goals/*` + workspaces parity) —
  **46 passed, 16 skipped** (every skip is a `MAISTRO_TEST_PG_DSN` leg);
  migrations modules (chain, installed-base, planner stability, task
  admission, invocation-effect) — **9 passed, 50 skipped** (pg-gated);
  `check-suite-inventory.py --suite packages/maistro-core/tests` — ok,
  14,685 node IDs; `check-m1-convergence-freeze.py --base df00785bb41b` —
  exit 0 (the issue's no-second-executor criterion).
- **Migration identity criterion holds at this head.** `alembic heads` is
  the single head `059` (`down_revision = "058"`); `056_user_model_facts`,
  `057_run_store_planner_stability` and `058_learning_validation_provenance`
  are byte-identical to base (empty diff over those paths); the two
  structural installed-base tests passed
  (`test_merged_ids_keep_their_meaning_and_goals_appends_after_them`,
  `test_restored_files_are_byte_identical_to_the_merged_snapshots`); both
  snapshot merge commits (`c560d4c`, `4675101`) are present in the clone.
- **PostgreSQL legs not executed this round (UNVERIFIED at this head
  locally).** `/var/run/docker.sock` is unreachable and the rootless
  `unix:///run/user/1000/docker.sock` used in round 13 hangs; both
  conformance pg legs and the four installed-base upgrade walks therefore
  skip pending a PostgreSQL environment (CI pg17/pg18 or a future round
  with the daemon up).
- **Production composition re-confirmed:** `create_container` wires
  `goal_store` via `wire_goal_store(db_pool, pg_pool=pg_pool)` and derives
  the authorized `goal_reader` seam; both shipped compositions call it
  (`packages/hive-conductor/backend/adapters/maistro_core.py`,
  `packages/maistro-server/src/maistro_server/main.py:344`).
- **No closure keywords** in any branch commit message or the PR body
  ("Refs #1572" only).
