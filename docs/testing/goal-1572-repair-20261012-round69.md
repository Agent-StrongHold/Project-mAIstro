# #1572 round-69 repair verification (2026-10-12, dispatch head `03580e2da3be`)

Driver instruction this round: "Previous block (resolve it as part of this round)" and
"Do not assume earlier verification claims are true." Both honored: every leg below was
re-derived or re-executed first-hand at this head. The driver's own checks
(job `86272e909e6e4e6db133`, `check-0..4.log` at this exact head) are green: `uv sync`
resolved, ruff check "All checks passed!", ruff format 3288 files clean, focused 9-file
pytest set 161 passed / 28 skipped, suite inventory ok (16334 identities).

## 0. Tree identity and the external world

- `git rev-parse HEAD` = `03580e2da3be51acadfff61c5e2a888af4cd8d32` (dispatch head;
  round-68's docs commit — the tree is code-identical to the round-58..68 battery tree).
- `git fetch origin` re-run this round: `origin/develop` =
  `3c761d14db944a727fa0744444bc67cfe36d49f7` == `git merge-base HEAD origin/develop`.
  **Nothing to merge; no GoalStatus grant has landed on develop**
  (`git grep GoalStatus origin/develop -- quality/` → no matches).
- Dispatch context (captured 2026-10-12T13:07:57Z) re-scanned: 501 comment objects,
  newest `2026-10-12T12:51:28Z`, all bot progress markers (started/blocked);
  **zero** GoalStatus mentions — no maintainer authorization signal.
- In-branch diffs to gates/CI re-read this round and confirmed additive/strengthening,
  not weakening: `ci.yml` +8 (new goals conformance CI step requiring PG legs),
  `quality.yml` +1 (goals suite added to the coverage producer list),
  `scripts/verify-wheel-imports.py` (adds `maistro.goals` to the public surface;
  pins sibling wheels via direct-reference constraints — strictly more deterministic),
  `quality/execution-lifecycles.json` +4 (the one floor-raising row, below).

## 1. The blocker, re-derived first-hand this round

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  `quality.yml` "execution lifecycles" step) → **exit 1**, sole finding:
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the
  trusted base and has no already-landed authorization` (19 classified → 20
  discovered; baseline printed `3c761d14db94`).
- `uv run pytest tests/test_check_execution_lifecycles.py` → **1 failed / 28 passed**;
  the failure is `test_the_shipped_ledger_matches_the_shipped_code` asserting
  `main() == 0` with the identical sole finding. This is the merge-queue
  `test: failure`; the coverage `combine` step inherits the dead producer.
- Mechanic re-read from source this round (not assumed):
  - `scripts/ratchet_provenance.py` `load_authorizations` reads the grant file
    **from the base revision**; docstring verbatim: "a new grant does not take effect
    in the change that introduces it. Authorizing a floor-raise is now two merges."
  - `resolve_baseline` precedence explicit > `RATCHET_BASE_REV` > GitHub event base >
    `origin/develop`, with `_refuse_self_reference`.
  - `_discover_at_revision` needs the module visible at base:
    `git cat-file -e 3c761d14db94:packages/maistro-core/src/maistro/goals/model.py`
    → exit 128 (module new in this branch), so base visibility is impossible.
  - `_unauthorized_additions` keeps the candidate's own ledger classification from
    self-authorizing an addition.
  - Therefore the gate fails **regardless of this branch's own ledger or grant file**:
    dropping the GoalStatus row fails `audit()` ("unclassified work-state
    vocabulary"); an in-branch grant is read from the base and is a no-op
    (`git diff origin/develop HEAD -- quality/ratchet-authorizations.json` = 0 lines,
    byte-identical). The #1572 scope mandates the
    ACTIVE/SATISFIED/CANCELLED/FAILED/SUPERSEDED vocabulary with CAS transitions the
    shipped suite exercises — removing/renaming it violates scope or dodges the
    detector. Editing the gate is prohibited weakening.
- Lane-brief "CI GATE REPAIR (vulture exact-debt-ledger)" exception re-checked at the
  exact CI argv (`quality.yml` vulture step):
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → **exit 0**, 1323 reviewed = 1323 findings,
  unclassified 0. **No amendment target exists.**

## 2. Acceptance criteria, executed first-hand this round

Environment: pgvector/pg18 container `maistro-postgres` (127.0.0.1:5433), fresh
databases `r69g18` (migrated), `r69chain`, `r69ib18`. `MAISTRO_REQUIRE_PG_LEGS=1`
plus both DSNs (`MAISTRO_TEST_PG_DSN`, `MAISTRO_TEST_DATABASE_URL` — plain
`postgresql://`; the conformance/wiring/binding suites read the former, the
schema-agreement suite the latter).

- **Migrations** — `uv run alembic upgrade head` on empty `r69g18` → single chain
  ending `062 -> 063, The canonical Goal store`; `alembic heads` → `063 (head)` only;
  `canonical_goals`, `canonical_goal_revisions`, `canonical_goal_transitions` all
  present (queried via asyncpg), stamp `063`.
- **AC1–AC6 + restart readback + schema agreement** —
  `uv run pytest packages/maistro-core/tests/goals -q` → **70 passed / 0 failed /
  0 skipped** with PG legs required: three-backend round-trip, append-only CAS
  one-winner, stale refusal, concurrent transitions, subgoal lineage, explicit
  recorded agent transition, two-principal workspace isolation, foreign == missing,
  immutable Run binding, Container wiring, restart readback, PG schema agreement.
- **AC7** — `uv run python scripts/check-m1-convergence-freeze.py --base
  3c761d14db944a727fa0744444bc67cfe36d49f7` (CI argv) → **exit 0**
  ("no unapproved new architecture island").
- **Migration chain** — `tests/migrations/test_migration_chain.py` on fresh
  `r69chain` → **18 passed** (includes the 063 downgrade/re-upgrade legs).
- **Installed-base boundary** — `tests/migrations/test_goal_installed_base_upgrade.py`
  on fresh `r69ib18` → **8 passed** (056/057 provenance byte-identity vs the
  develop snapshots, forward upgrade with no stamp edit, planner CHECK intact).
- **Typecheck** — `uv run mypy packages/{maistro-core,maistro-server,maistro-turing,
  maistro-canvas,maistro-bootstrap,maistro-registry,maistro-ext-sdk}/src` →
  **Success: no issues found in 899 source files**.
- **Ruff** — driver `check-1/2.log` at this head: check "All checks passed!",
  format 3288 files clean.

## 3. Local-only failure (unchanged, left untouched)

`tests/test_branch_independence_repository.py::
test_every_quality_json_state_surface_is_classified_once` fails in this worktree only
via the untracked gitignored scratch file `quality/ac-state.json` (2026-10-11,
`.gitignore:81`) found by the unconditional rglob in
`scripts/check-branch-independence.py:206`. CI passed it; the file is prior salvage
and was again left untouched.

## 4. Verdict

**BLOCKED** — identical to rounds 58–68 and re-proven this round: the only failing
gate evidence is the external `execution-lifecycles` authorization for
`maistro.goals.model::GoalStatus`, which by design (`load_authorizations` reads the
base revision) cannot be satisfied inside this branch. All seven issue acceptance
criteria plus the migration and installed-base closure boundaries are proven by
executed tests above; the authorization closure item is external. Required unblock
action (unchanged): a maintainer lands an `execution-lifecycles` grant for
`maistro.goals.model::GoalStatus` on develop (the #1833 two-merge precedent — an
open grant-only PR such as #1938's head `2f5dd46969fc` is exactly that shape), then
this branch merges develop; the gate and
`test_the_shipped_ledger_matches_the_shipped_code` pass with **zero edits** here.

Docs-only change; no code, test, or ledger edits; no inventory delta (no tests added
or removed this round).
