# #1572 repair round 67 — 2026-10-12 (job 047537921f184e7d9b48669744001d38)

Dispatch head `6bd23bf9225b45af01b955d72dd5ef05d5bf994c` (branch `auto-1572`), base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. `git diff db091060d..HEAD --name-only`
is 9 `.md` files only (rounds 58–66 verification notes), so the shipped code —
`packages/maistro-core/src/maistro/goals/*`, `alembic/versions/063_canonical_goals.py`,
both quality ledgers — is byte-identical to the tree every prior PG battery
validated. The driver's five checks in this job's own `check-*.log` are green at
this head: `uv sync --locked --extra dev` ok, `ruff check .` all checks passed,
`ruff format --check .` 3288 files already formatted, focused 9-file pytest set
161 passed/28 skipped, suite inventory ok (16334 unique identities, 0 duplicate).

The driver instruction this round was "resolve the BLOCKED as part of this round";
per the anti-assumption rule every leg below was re-derived first-hand at this
exact head, including a fresh `git fetch origin`.

## Sole blocker, re-proven at this exact head

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  quality.yml:1541 "execution lifecycles (no unclassified second spine)") exits 1:
  baseline `base 3c761d14db94`, candidate `6bd23bf9225b`,
  `19 classified lifecycles -> 20 discovered lifecycles`, sole finding
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the
  trusted base and has no already-landed authorization`.
- `uv run pytest tests/test_check_execution_lifecycles.py -q` → `1 failed, 28
  passed`; the sole failure `test_the_shipped_ledger_matches_the_shipped_code`
  asserts `main() == 0` and fails on the same finding. This IS the merge-queue
  `test: failure`; the coverage `combine` step only inherits the dead producer.
- Why no in-branch repair exists (read from source this round, not assumed):
  - `load_authorizations` (scripts/ratchet_provenance.py:478-495) reads
    `quality/ratchet-authorizations.json` from the **base revision**; its
    docstring states the two-merge consequence verbatim ("a new grant does not
    take effect in the change that introduces it ... two merges -- the grant,
    then the regression it permits").
  - `resolve_baseline` (scripts/ratchet_provenance.py:301) precedence is explicit
    > `RATCHET_BASE_REV` > GitHub event base > `origin/develop`, behind
    `_refuse_self_reference` (:258) which refuses a base that names HEAD.
  - `_discover_at_revision` (scripts/check-execution-lifecycles.py:662-690) needs
    `git show <base>:packages/maistro-core/src/maistro/goals/model.py` to
    succeed; re-proven absent: `git cat-file -e
    3c761d14db94:packages/maistro-core/src/maistro/goals/model.py` →
    `fatal: ... exists on disk, but not in '3c761d14db94'` (exit 128).
  - `_unauthorized_additions` (:705-707) deliberately keeps the candidate's own
    DOMAIN classification (present in the candidate ledger with a full
    rationale) from self-authorizing.
  - The in-branch grant (2f5dd4696) was empirically a no-op (round 59);
    `cmp` of `quality/ratchet-authorizations.json` HEAD vs base confirms the
    file is byte-identical to origin/develop again (no trailing-newline
    divergence: base itself ends without one, so "restoring" it would diverge).
- No authorization has landed upstream: `git fetch origin` re-run this round;
  `git rev-parse origin/develop` = `3c761d14db944a727fa0744444bc67cfe36d49f7` ==
  merge-base (develop has NOT moved; nothing to sync). develop's only
  execution-lifecycles grants are `services.rsi::RunStatus` and
  `maistro.graph.nodes.agent_delegate_remote::DelegationStatus` (#1136); zero
  GoalStatus grants.
- Lane-brief vulture CI-repair exception has NO target:
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (exact CI argv,
  quality.yml:1079) exits 0, `1323 reviewed identities -> 1323 findings`,
  unclassified 0. Nothing to amend in `quality/vulture-baseline.json`.
- Vocabulary removal/rename would violate the issue-mandated lifecycle
  ("active, satisfied, cancelled, failed, superseded", CAS transitions, terminal
  states final) or dodge the `_MIN_WORK_STATES = 3` detector; both are prohibited
  gate weakening. No develop sync conflict exists (develop unchanged), so the
  lane's merge instruction has nothing to merge.

Required external action (unchanged from rounds 58–66): a maintainer lands the
execution-lifecycles grant for `maistro.goals.model::GoalStatus` on develop first
(owner/issue/reason record under `execution-lifecycles` in
`quality/ratchet-authorizations.json`, per the two-merge rule; vulture-identity
PR #1833 is the landed precedent), after which this branch merges develop and
gate + shipped-ledger test pass with zero edits.

## Acceptance legs re-executed first-hand this round (fresh pg18.6, port 5433)

- Fresh database `r67g18`: `alembic upgrade head` empty → single head `063`
  ending `062 -> 063, The canonical Goal store`; `alembic current` = `063 (head)`.
- `packages/maistro-core/tests/goals` +
  `packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py`
  with `MAISTRO_REQUIRE_PG_LEGS=1` and `MAISTRO_TEST_PG_DSN` ==
  `MAISTRO_TEST_DATABASE_URL`: **72 passed, 0 skipped** (3-backend conformance,
  append-only CAS one winner, stale-revision refusal, subgoal lineage,
  foreign==missing authorization, immutable run binding, migration-063 vs
  ensure-schema agreement, restart readback, shipped Container wiring). Note: an
  intermediate 66p/6-error run was this operator's own shell expansion mistake
  (`export A=.. B="$A"` in one command left `MAISTRO_TEST_DATABASE_URL` empty);
  with the variable actually set the suite is fully green.
- Downgrade `alembic downgrade 062` drops the three `canonical_goal*` tables
  (3 → 0) and re-`upgrade head` restores them (0 → 3), stamp back at `063`.
- `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py -q` with
  PG legs required: **8 passed** on the actual develop snapshots (`c560d4c`,
  `4675101` both present in the clone) — merged identities keep meaning and
  ancestry, `063` appends after integrated head `062`, `git diff base..HEAD` on
  `056_user_model_facts.py`/`057_run_store_planner_stability.py` is empty.
- `uv run python scripts/check-m1-convergence-freeze.py --base
  3c761d14db944a727fa0744444bc67cfe36d49f7` (CI argv, formal-conformance.yml:77)
  exits 0: "no unapproved new architecture island".
- `uv run mypy` on all seven package src trees: clean, 899 source files.
- Full `uv run pytest packages/maistro-core/tests -q`: **15264 passed, 1067
  skipped, 3 xfailed** — no regression beyond the known external blocker.
- Production composition re-read at this head: `container.py:44` imports
  `wire_goal_store` from `maistro.goals.wiring`, `container.py:2414` composes
  `goal_store` in `create_container`; `test_goal_wiring.py` proves the shipped
  Container exposes it.

No code, test, or ledger changes this round (docs-only), so no inventory delta.
Local-only branch-independence failure cause re-confirmed: untracked,
gitignored scratch `quality/ac-state.json` — left untouched.
