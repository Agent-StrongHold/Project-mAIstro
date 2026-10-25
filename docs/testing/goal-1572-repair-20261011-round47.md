# #1572 repair — round 47 verification and writer record (head dd50e19943a52)

Lane L1572, job `420d04c8…` (420d04c8887d4b94a135903436683cc0). Round 46 ended
with **no verdict** (provider timeout after green driver checks, no tree
change); this round re-executed every load-bearing check first-hand at
`dd50e19943a52bf71ce6e51c6e1d07beb4b8b8d0` and commits this record.

## Carry-in proof

`git diff --name-only e7e4d341b6b71b0483dd50d2203fbca8cea531db..HEAD` lists
exactly 10 files, all `docs/testing/goal-1572-repair-2026101-round3[7-9|4*].md`
round notes — **0 non-docs diffs**, so the code, tests, migrations and ledgers
are byte-identical to the round-37 fully-validated tree. Round 37-46 evidence
carries; everything below was nevertheless re-run at this head.

## Driver deterministic checks (this job's `check-*.log`)

`uv sync --locked --extra dev` exit 0; `ruff check .` exit 0; `ruff format
--check .` exit 0 (3288 files); focused pytest (9-file goals/events/extensions/
workspaces set) **161 passed, 28 skipped**; `check-suite-inventory.py --suite
packages/maistro-core/tests` → **ok, 16334 identities, 0 duplicates**.

## Acceptance re-executed first-hand at dd50e1994

Fresh round-47 database `r47g18` (PostgreSQL **18.6**, container
`auto-1572-pg`, 127.0.0.1:55712), created empty:

- `DATABASE_URL=…/r47g18 uv run alembic upgrade head` → **exit 0**, chain
  empty → 063, final step `062 -> 063, The canonical Goal store:
  canonical_goals and its append-only children`; `alembic_version` = **063**;
  `canonical_goals`, `canonical_goal_revisions`, `canonical_goal_transitions`
  catalog-verified (`pg_tables`).
- `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=…/r47g18
  MAISTRO_TEST_DATABASE_URL=…/r47g18 uv run pytest
  packages/maistro-core/tests/goals -q` → **70 passed, 0 skipped** (memory +
  SQLite + PostgreSQL through the one conformance suite; append-only/CAS,
  Subgoal lineage, Run-binding immutability, cross-Workspace
  foreign==missing, shipped-Container wiring, restart readback, pg catalogue
  agreement — legs enforced, no silent skip).
- `uv run python scripts/check-m1-convergence-freeze.py --base
  3c761d14db944a727fa0744444bc67cfe36d49f7` → **exit 0** ("no unapproved new
  architecture island") — no `GoalRun`/`OrchestratorRun`/second
  executor/product-private Goal lifecycle.
- Vulture at CI argv: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → **exit 0**,
  `1323 reviewed identities -> 1323 findings`; no unbanked identities, no
  `quality/vulture-baseline.json` amendment applies in this round.

Carried by the byte-identity proof (first-hand in rounds 44-46 on identical
bytes): pg17 leg 70/70 (`r45g17`), installed-base forward upgrades
`c560d4c`→user-model 056 and `4675101`→planner 057 from real develop snapshot
trees with no stamp edit on both majors (facts/keys survive, planner
`ck_canonical_runs_status`/`ck_canonical_node_runs_status` intact, restart
readback 11/11), fresh-install single-head/unique-identity + downgrade/refusal
inside the 168-test migrations battery, `mypy --strict` clean.

## The three merge-queue reds — one root cause, all re-proven this round

1. **Gate**: `RATCHET_BASE_REV=origin/develop uv run python
   scripts/check-execution-lifecycles.py` (exact CI argv, `quality.yml:1541`)
   → **exit 1**: base `3c761d14db94`, `19 classified lifecycles -> 20
   discovered lifecycles`, sole finding `maistro.goals.model::GoalStatus: NEW
   work-state vocabulary is absent from the trusted base and has no
   already-landed authorization`.
2. **test job**: `RATCHET_BASE_REV=origin/develop uv run pytest
   tests/test_check_execution_lifecycles.py -q` → **1 failed, 28 passed**;
   the failure is
   `test_the_shipped_ledger_matches_the_shipped_code` (`assert gate.main()
   == 0`, tests/test_check_execution_lifecycles.py:374) with the identical
   GoalStatus stdout.
3. **Coverage gate**: job log re-fetched read-only (`gh api
   …/actions/jobs/114493390309/logs`) this round: publish-set floor passed;
   the run died in the `pytest tests/` producer on the **same** single test
   (`1 failed, 5081 passed, 135 skipped`); diff-coverage never ran.

## Sole blocker — unchanged and external; sufficiency re-proven mechanically

- `git fetch origin` + `git ls-remote origin develop` this round → develop is
  **still** `3c761d14db944a727fa0744444bc67cfe36d49f7`. No sync conflict; the
  grant-only GoalStatus authorization has not landed.
- Two-merge mechanics re-read in source: authorizations are read **from the
  merge base** (`scripts/ratchet_provenance.py:477` docstring "a new grant
  does not take effect in the change that introduces it";
  `scripts/check-execution-lifecycles.py:773` calls
  `prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)`), so the
  branch's own `quality/execution-lifecycles.json` GoalStatus row and any
  candidate-side `ratchet-authorizations.json` edit structurally cannot
  authorize it.
- **Sufficiency re-proven this round with no tree edit**: the gate module was
  loaded unmodified via `importlib` (registering `ratchet_provenance` under
  its private name `_ratchet_provenance`) with the *only* delta an in-memory
  `execution-lifecycles: maistro.goals.model::GoalStatus` grant injected into
  `load_authorizations` — exactly what a grant-only develop landing provides
  at the base. Result: **exit 0** — `OK: 20 work-state vocabularies, all
  classified (3 CANONICAL, 8 CONVERGE, 7 DOMAIN, 2 PROJECTION)` with the
  authorization line printed.
- No in-branch edit can legitimately flip this gate: a self-grant on this
  branch is unread by design; deleting the classification fails the candidate
  audit; deleting the enum guts the issue's required Goal lifecycle; renaming
  enum members to dodge the work-state detector would weaken the gate. None
  of these is a repair. The vulture-ledger CI-repair exception does not reach
  `execution-lifecycles` (and the vulture ledger is green anyway).
- Grant text for the owner to land on develop is in the round-37 record and
  remains accurate verbatim.

## Process hygiene

- No closure keywords: dispatch-context capture (this job, 2026-10-11T21:07Z)
  shows PR #1938 still **open** at `30f9fc5d74e7`; no GitHub mutation
  performed or requested.
- No code, test, or ledger changes this round → no suite-inventory delta, no
  `docs/testing/inventory-notes/` entry required (driver check-4 already
  matched the recorded baseline).
- Verdict: **BLOCKED** — candidate complete and green on every executed leg;
  the three red merge-queue checks share the one two-merge root cause whose
  only unblock is the grant-only
  `execution-lifecycles: maistro.goals.model::GoalStatus` authorization
  landing on develop (outside lane authority). Once landed, merge develop
  into this branch and re-run the queue; no other change is needed.
