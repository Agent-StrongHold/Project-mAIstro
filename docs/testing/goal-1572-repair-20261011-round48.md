# #1572 repair — round 48 verification and writer record (head e92505ea64dc)

Lane L1572, job `14e632f581cd4d6d87e3ba789ce1fc29`. Round 47's driver job
(fb933656…) executed all five deterministic checks green and then died on a
provider timeout before emitting a verdict; this round re-executed every
load-bearing check first-hand at the identical head `e92505ea64dc` and commits
this record. No tree edit was made before the final note+commit.

## Carry-in proof

`git diff --name-only e7e4d341b6b71b0483dd50d2203fbca8cea531db..HEAD` lists
exactly 11 files, all `docs/testing/goal-1572-repair-20261011-round{37..47}.md`
round notes — **0 non-docs diffs**, so code, tests, migrations and ledgers are
byte-identical to the round-37 fully-validated tree. Rounds 37-47 evidence
carries; everything below was nevertheless re-run at this head.

## Driver deterministic checks (this job's `check-*.log`)

`uv sync --locked --extra dev` exit 0; `ruff check .` exit 0 ("All checks
passed!"); `ruff format --check .` exit 0 (3288 files); focused pytest (9-file
goals/events/extensions/workspaces set) **161 passed, 28 skipped**;
`check-suite-inventory.py --suite packages/maistro-core/tests` → **ok, 16334
identities, 0 duplicates**.

## Acceptance re-executed first-hand at e92505ea64dc

Fresh round-48 database `r48g18` (PostgreSQL **18.6**, container
`auto-1572-pg`, 127.0.0.1:55712), created empty:

- `DATABASE_URL=…/r48g18 uv run alembic upgrade head` → **exit 0**, chain
  empty → 063, final step `062 -> 063, The canonical Goal store: canonical_goals
  and its append-only children`; `alembic_version` = **063**;
  `canonical_goals`, `canonical_goal_revisions`, `canonical_goal_transitions`
  catalog-verified (`pg_tables`); `alembic heads` → single head **063**;
  `063_canonical_goals.py` has `revision = "063"`, `down_revision = "062"`;
  `git diff origin/develop HEAD -- alembic/versions/0056*.py 0057*.py` →
  byte-identical (exit 0).
- `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=…/r48g18
  MAISTRO_TEST_DATABASE_URL=…/r48g18 uv run pytest
  packages/maistro-core/tests/goals -q` → **70 passed, 0 skipped** (memory +
  SQLite + PostgreSQL through the one conformance suite; append-only/CAS,
  Subgoal lineage, Run-binding immutability, shipped-Container wiring, restart
  readback, pg catalogue agreement — legs enforced, no silent skip).
  Env-var trap recorded for future rounds: **both** DSN vars must be plain
  `postgresql://` — `MAISTRO_TEST_DATABASE_URL` is fed straight to asyncpg
  (`test_goal_pg_schema_agreement.py:38`), so a `postgresql+asyncpg://` value
  errors 6 schema-agreement setups (first-hand this round; 64p/6e before the
  fix, 70/0 after).
- `uv run python scripts/check-m1-convergence-freeze.py --base
  3c761d14db944a727fa0744444bc67cfe36d49f7` → **exit 0** ("no unapproved new
  architecture island").
- Vulture at CI argv: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → **exit 0**,
  `1323 reviewed identities -> 1323 findings`; no unbanked identities, no
  `quality/vulture-baseline.json` amendment applies in this round.
- Production composition re-read: `maistro/container.py:44` imports
  `wire_goal_store`, `:2414` calls it inside `create_container`, `:273`
  `goal_store` field, `:277-286` `goal_reader` → `ScopedGoalStore`
  (principal-carrying seam, foreign-Goal-answers-missing); Hive adapter
  `packages/hive-conductor/backend/adapters/maistro_core.py:195` and
  `packages/maistro-server/src/maistro_server/main.py:344` both build through
  `create_container`, so the wired Goal store is the production one.

## The three merge-queue reds — one root cause, re-proven this round

1. **Gate**: `uv run python scripts/check-execution-lifecycles.py` (exact CI
   argv, `quality.yml:1541`, no env override — the script bases itself on
   `origin/develop` internally) → **exit 1**: base `3c761d14db94`,
   `19 classified lifecycles -> 20 discovered lifecycles`, sole finding
   `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from
   the trusted base and has no already-landed authorization`.
2. **test job**: `uv run pytest tests/test_check_execution_lifecycles.py -q`
   → **1 failed, 28 passed**; the failure is
   `test_the_shipped_ledger_matches_the_shipped_code`
   (`assert gate.main() == 0`, tests/test_check_execution_lifecycles.py:374)
   with the identical GoalStatus stdout. `tests/` is the Coverage gate's
   pytest producer (round 47 read the job log: `1 failed, 5081 passed`,
   diff-coverage never ran), so red #3 is this same single test.
3. Ledger states re-read: branch `quality/execution-lifecycles.json:89` banks
   `maistro.goals.model::GoalStatus` (DOMAIN, 20 rows total); develop base has
   **19** rows and no GoalStatus row; **neither** the base nor the branch
   `quality/ratchet-authorizations.json` has an `execution-lifecycles:
   maistro.goals.model::GoalStatus` grant.

## Sole blocker — unchanged and external; sufficiency re-proven mechanically

- `git fetch origin` + `git ls-remote origin develop` this round → develop is
  **still** `3c761d14db944a727fa0744444bc67cfe36d49f7`. No sync conflict to
  merge; the grant-only GoalStatus authorization has not landed.
- Two-merge mechanics re-read in source: `check-execution-lifecycles.py:773`
  calls `prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)`;
  `ratchet_provenance.py:477-495` (AUTHORIZATIONS at `:474`) — "Read **from
  the base revision**… a new grant does not take effect in the change that
  introduces it. Authorizing a floor-raise is now two merges." The branch's
  own ledger row and any candidate-side authorization edit are structurally
  unread.
- **Sufficiency re-proven this round with no tree edit**: the real
  `ratchet_provenance.py` was loaded unmodified as `_ratchet_provenance`, the
  *only* delta an in-memory `execution-lifecycles:
  maistro.goals.model::GoalStatus` grant wrapped around
  `load_authorizations` (exactly what a grant-only develop landing supplies
  at the base), then the unmodified gate's `main()` ran → **exit 0** —
  `OK: 20 work-state vocabularies, all classified (3 CANONICAL, 8 CONVERGE,
  7 DOMAIN, 2 PROJECTION)` with the authorization line printed. Working tree
  confirmed clean afterward.
- No in-branch edit can legitimately flip this gate: a self-grant on this
  branch is unread by design; deleting the classification fails the candidate
  audit; deleting the enum guts the issue's required Goal lifecycle; renaming
  enum members to dodge the work-state detector would weaken the gate. None
  of these is a repair. The vulture-ledger CI-repair exception does not reach
  `execution-lifecycles` (and the vulture ledger is green, 1323=1323).
- Grant text for the owner to land on develop is in the round-37 record and
  remains accurate verbatim.

## Fresh dispatch context scanned (captured 2026-10-11T21:31-21:35Z)

Issue #1572 **open** (updated 21:16:13Z, 311 comments); PR #1938 still
**open** at `30f9fc5d74e7`, PR #1855 open at `3f2c79a70d9e`; latest issue
comments are this lane's own blocked/started progress markers — no new human
instruction, no closure keyword, no landed grant.

## Process hygiene

- No code, test, or ledger changes this round → no suite-inventory delta, no
  `docs/testing/inventory-notes/` entry required (driver check-4 already
  matched the recorded baseline at 16334).
- No GitHub mutation performed or requested.
- Verdict: **BLOCKED** — candidate complete and green on every executed leg;
  the three red merge-queue checks share the one two-merge root cause whose
  only unblock is the grant-only
  `execution-lifecycles: maistro.goals.model::GoalStatus` authorization
  landing on develop (outside lane authority). Once landed: merge develop
  into this branch, re-run the queue — no other change is needed.
