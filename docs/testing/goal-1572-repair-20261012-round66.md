# #1572 repair round 66 — 2026-10-12 (job f85d461f2b97489dae999b4cb96aa8fe)

Dispatch head `b6e74c29ec193df3b762448cfdcaf0fdaaa4dfc6` (branch `auto-1572`), base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. `git diff --stat db091060d..HEAD` is 8
docs-only files (rounds 58–65 verification notes), so the shipped code — including
`alembic/versions/063_canonical_goals.py` — is byte-identical to the tree every prior
PG battery validated. The driver's five checks in this job's own `check-*.log` are
green at this head: `uv sync --locked --extra dev` ok, `ruff check .` all checks
passed, `ruff format --check .` 3288 files already formatted, focused 9-file pytest
set 161 passed/28 skipped, suite inventory ok (16334 unique identities, 0 duplicate).

This round re-derived every claim first-hand instead of trusting any prior round, and
re-ran the durable legs on a fresh pg18 database.

## Sole blocker, re-proven at this exact head

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  quality.yml:1541 "execution lifecycles (no unclassified second spine)") exits 1:
  baseline `base 3c761d14db94`, candidate `b6e74c29ec19`,
  `19 classified lifecycles -> 20 discovered lifecycles`, sole finding
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the
  trusted base and has no already-landed authorization`.
- `uv run pytest tests/test_check_execution_lifecycles.py -q` → `1 failed, 28 passed`;
  the sole failure `test_the_shipped_ledger_matches_the_shipped_code` asserts
  `main() == 0` and fails on the same finding. This IS the merge-queue `test:
  failure`; the coverage `combine` step only inherits the dead producer (no
  independent floor or diff-coverage deficit).
- Why no in-branch repair exists (read from source this round, not assumed):
  `load_authorizations` (scripts/ratchet_provenance.py:478-495) reads
  `quality/ratchet-authorizations.json` from the **base revision**; its docstring
  states the two-merge consequence verbatim ("a new grant does not take effect in
  the change that introduces it ... two merges -- the grant, then the regression it
  permits"). `resolve_baseline` (scripts/ratchet_provenance.py:301) precedence is
  explicit > `RATCHET_BASE_REV` > GitHub event base > `origin/develop`, behind
  `_refuse_self_reference`; and `_discover_at_revision` needs `git show
  <base>:packages/maistro-core/src/maistro/goals/model.py` to succeed, which it
  cannot — the module is new in this branch. `_unauthorized_additions` deliberately
  keeps the candidate's own DOMAIN classification from self-authorizing. The
  in-branch grant (2f5dd4696, open PR #1938) was empirically a no-op (round 59) and
  the file is byte-identical to origin/develop again.
- No authorization has landed upstream: `git fetch origin` then
  `git rev-parse origin/develop` = `3c761d14db94…` == merge-base (develop has NOT
  moved); `git grep GoalStatus origin/develop -- quality/` = no matches; develop's
  only execution-lifecycles grants are `services.rsi::RunStatus` and
  `maistro.graph.nodes.agent_delegate_remote::DelegationStatus` (#1136). The newest
  issue comments/timeline through 2026-10-12T11:05:52Z are bot progress markers
  only — no maintainer authorization.
- Lane-brief vulture CI-repair exception has NO target:
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (exact CI argv, quality.yml:1079)
  exits 0, `1323 reviewed identities -> 1323 findings`, unclassified 0.
- No develop sync conflict exists (develop unchanged), so the lane's merge
  instruction has nothing to merge; vocabulary removal/rename would violate the
  issue-mandated lifecycle (CAS transitions, terminal states final) or dodge the
  `_MIN_WORK_STATES = 3` detector, and both are prohibited gate weakening.

Required external action (unchanged from rounds 58–65): a maintainer lands the
execution-lifecycles grant for `maistro.goals.model::GoalStatus` on develop first
(owner/issue/reason record in `quality/ratchet-authorizations.json`, per the two-merge
rule; vulture-identity PR #1833 is the landed precedent), after which this branch
merges develop and the gate + shipped-ledger test pass with zero branch edits.

## Acceptance legs re-executed first-hand this round (pg18, fresh databases)

- Fresh DB `r66g18` on the healthy `maistro-postgres` (pgvector/pgvector:pg18,
  127.0.0.1:5433): `DATABASE_URL=… DATABASE_URL… uv run alembic upgrade head`
  migrates empty → single head, final line `Running upgrade 062 -> 063, The canonical
  Goal store: canonical_goals and its append-only children`.
- `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=…r66g18
  MAISTRO_TEST_DATABASE_URL=…r66g18 uv run pytest packages/maistro-core/tests/goals
  -q` → **70 passed, 0 skipped** on pg18 (memory/sqlite/postgres conformance round-
  trip, append-only CAS with exactly one concurrent winner and stale-revision
  refusal, Subgoal lineage + explicit recorded Agent reassignment, two-principal/
  two-Workspace isolation with foreign == missing, immutable Run binding, schema
  agreement, durable restart readback, shipped Container wiring). First attempt on
  the long-lived shared `maistro` DB errored 3 postgres legs with
  `UndefinedTableError: relation "canonical_projects" does not exist` — dirty-DB
  artifact of reusing a non-migrated shared database, not a code defect; green on the
  freshly migrated DB.
- `uv run pytest packages/maistro-core/tests/runs packages/maistro-core/tests/events
  -q` with PG legs required → **1888 passed, 3 skipped** on pg18 (run admission
  binding and its immutability live here).
- Fresh DB `r66chain`: `uv run pytest tests/migrations/test_migration_chain.py -q` →
  **18 passed** (includes the 063 downgrade dropping the 3 `canonical_goal*` tables
  then re-upgrade restoring them).
- `git ls-tree origin/develop -- alembic/versions/` tops out at
  `062_audit_cursor_indexes.py`; `063_canonical_goals.py` (`revision = "063"`,
  `down_revision = "062"`) is branch-only — no head collision, nothing to sync. (An
  earlier quick check that printed "063 EXISTS ON DEVELOP" was a shell-glob artifact
  of `git show origin/develop:alembic/versions/063*` expanding against the local
  tree; `git ls-tree` is authoritative.) `git diff origin/develop..HEAD --
  alembic/versions/056_user_model_facts.py alembic/versions/057_run_store_planner_stability.py`
  is empty (installed-base snapshots byte-identical to develop).
- `uv run python scripts/check-m1-convergence-freeze.py --base
  3c761d14db944a727fa0744444bc67cfe36d49f7` (CI argv, formal-conformance.yml:77) →
  exit 0, "no unapproved new architecture island".
- `uv run mypy packages/maistro-core/src … packages/maistro-ext-sdk/src` → Success,
  no issues in 899 source files.
- Known local-only failure re-confirmed, not a branch defect:
  `tests/test_branch_independence_repository.py::
  test_every_quality_json_state_surface_is_classified_once` fails in this worktree
  only because the untracked, gitignored scratch `quality/ac-state.json`
  (.gitignore:81) is seen by the gate's unconditional rglob; CI passed this test.
  Scratch left untouched.

## Criterion → evidence map (all criteria have shipped tests; statuses at this head)

1. Goal/GoalRevision round-trip on all three backends (shared conformance suite) →
   `test_goal_store_conformance.py` legs inside the 70-passed pg18 run. PROVEN.
2. Append-only revisions; stale-revision refused; concurrent update has one winner →
   same conformance legs. PROVEN.
3. Subgoal lineage preserves parent Goal and Project; owning-Agent change is an
   explicit recorded transition → same conformance legs. PROVEN.
4. Run admission binds `goal_id`/`goal_revision`, immutable after admission →
   `test_run_goal_binding.py` (goals 70p) + runs/events 1888p. PROVEN.
5. Two principals in two Workspaces isolated; foreign Goal == missing Goal →
   conformance isolation legs. PROVEN.
6. Production composition wires the store; shipped Container exposes it →
   `test_goal_wiring.py` in the 70p run (Hive + maistro-server compositions re-read
   in rounds 62/64 at this code-identical tree). PROVEN.
7. No `GoalRun`/second executor/product-private lifecycle → convergence freeze exit 0
   at CI argv. PROVEN.
8. Migrations + installed-base upgrade boundary → this round: empty→063 single head
   on fresh pg18, chain test 18p incl. downgrade/re-upgrade, 056/057 byte-identical
   to develop, no head collision; installed-base forward-upgrade legs (c560d4c→056,
   4675101→057) proven rounds 60–62 at this byte-identical migration set. PROVEN.
9. Closure-boundary authorization item → **UNPROVEN, external**: the execution-
   lifecycles ratchet requires a separately landed grant on develop for
   `maistro.goals.model::GoalStatus` (two-merge rule). Not satisfiable in-branch by
   design (see above); PR #1833 is the landed precedent for this exact flow.

Verdict: **BLOCKED** on the external maintainer execution-lifecycles grant for
`maistro.goals.model::GoalStatus` landing on develop, then a develop merge into this
branch. Zero branch edits are required or permitted for that step (gate/ledger edits
by the candidate are self-authorization by construction). No code, test, or ledger
changes this round; docs-only note, no inventory delta (no tests added).
