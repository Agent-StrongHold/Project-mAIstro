# #1572 repair lane — round 60 verification (2026-10-12)

Head `8510776aef384f0334cdddd7192ad1c7407ad7a5` (branch `auto-1572`), base
`3c761d14db944a727fa0744444bc67cfe36d49f7` (== merge-base; origin/develop
fetched and unchanged this round).

## The repair: restore `quality/ratchet-authorizations.json` structure

Commit `8510776ae` ("Remove incorrect GoalStatus authorization ...") removed
the in-branch `maistro.goals.model::GoalStatus` grant (correct per the
two-merge rule) but **also deleted the `"execution-lifecycles"` section
closer**, nesting `"promotion-surface"` inside it. Concretely, against
`db091060d` the commit replaced

```
    }
  },
  "promotion-surface": {
```

with

```
    },
  "promotion-surface": {
```

leaving the file **invalid JSON** (`json.loads`: "Expecting ',' delimiter:
line 1817 column 2"). Attribution across heads: `db091060d` VALID,
`2f5dd4696` VALID (grant added, trailing newline dropped), `8510776ae`
INVALID. No driver check caught it: the ratchet gates read grants from the
**base revision** (`ratchet_provenance.load_authorizations`,
`scripts/ratchet_provenance.py:478-495`), so the corrupt *candidate* copy is
invisible to them, and the provenance unit tests use synthetic repos.

Repair applied this round: the file is restored **byte-identical to
`db091060d` and to `origin/develop`** (both verified with `cmp`), which
completes the intended grant removal, restores valid JSON and the trailing
newline, and un-blocks the two-merge path (a maintainer-side grant on develop
at exactly this location now merges cleanly instead of conflicting with a
mangled copy). Post-repair, `git diff --numstat origin/develop -- quality/`
is additive-only with this file absent: `17/0` ac-state-notes, `39/0`
durable-table-retention, `4/0` execution-lifecycles. The candidate ledger
classification of `GoalStatus` in `quality/execution-lifecycles.json:89`
stays — that row is the change under review; its *authorization* must land on
develop first.

After this repair the head is docs-only over `db091060d` for all production
code, tests, migrations and quality ledgers, so the rounds 37–59 batteries
carry byte-identically; this round nevertheless re-executed the core battery
first-hand (below).

## Driver checks at this head (green)

- `uv run ruff check .` — "All checks passed!"; `ruff format --check .` —
  3288 files already formatted (re-run post-repair).
- 9-file pytest set (driver job `46cf9abee8ba` check-3.log) — **161 passed,
  28 skipped**; the 28 skips are the PG legs, force-run live below.
- Suite inventory (check-4.log) — ok, 16334 collected node IDs, matches the
  recorded baseline; no inventory delta this round (no tests added).

## Gates

- `check-execution-lifecycles` at exact CI argv (quality.yml:1541) — **exit
  1, sole finding**: `maistro.goals.model::GoalStatus: NEW work-state
  vocabulary is absent from the trusted base and has no already-landed
  authorization` (19→20). Unchanged by the repair and **external**: the gate
  reads grants from base `3c761d14db94`, which carries 0 GoalStatus grants
  (`git show origin/develop:quality/ratchet-authorizations.json | grep -ci
  goalstatus` = 0). Per `ratchet_provenance.py:478-495` a grant only takes
  effect from the merge base — land the grant on develop first, then this
  branch. No legitimate in-branch path exists (removing/renameing the
  vocabulary would gut the issue's lifecycle scope; hiding it from the
  scanner would weaken the gate). This is the round-55–59 conclusion,
  re-proven first-hand.
- `tests/test_check_execution_lifecycles.py` — **1 failed / 28 passed**;
  `test_the_shipped_ledger_matches_the_shipped_code` fails on the same sole
  cause (CI's red test job; the coverage `combine` step inherits it). The
  candidate-side `audit()` findings list is empty — the classification and
  rationale are correct; only the trusted-base authorization is missing.
- Vulture CI-repair lane at exact CI argv: `uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — **exit 0**, 1323 reviewed = 1323 findings,
  unclassified 0. Nothing to amend in `quality/vulture-baseline.json`.
- `check-m1-convergence-freeze.py --base 3c761d14db94` (formal-conformance
  yml:77 argv) — **exit 0**: no `GoalRun`, no second executor, no
  product-private Goal lifecycle.

## Acceptance legs re-executed first-hand (post-repair working tree)

- **Fresh migrations, both majors:** lane containers `auto-1572-pg` (pg18,
  :55712) / `auto-1572-pg17` (pg17, :55717); throwaway databases `r60g18` /
  `r60g17` migrated **empty → head**, final line `062 -> 063, The canonical
  Goal store`; `alembic heads`/`current` = 063 single head; all three
  `canonical_goal*` tables (`canonical_goals`, `_revisions`, `_transitions`)
  present on both majors.
- **Goals + events, PG legs forced** (`MAISTRO_REQUIRE_PG_LEGS=1`,
  `MAISTRO_TEST_PG_DSN` + `MAISTRO_TEST_DATABASE_URL` at `r60g18`) —
  **453 passed, 0 skipped**: conformance across memory/sqlite/postgres,
  append-only revisions with CAS (exactly one concurrent winner), stale
  revision refused, subgoal lineage preserving parent Goal and Project,
  ownership change as explicit recorded transition, foreign Goal ==
  missing Goal, immutable `goal_id`/`goal_revision` Run binding, Workspace
  isolation, PG schema agreement, restart readback (criterion-to-test map as
  in rounds 57–59).
- **Goals-only at `r60g17`** (second supported major) — **70 passed,
  0 skipped**.
- **Downgrade/reapplication** on `r60g18`: `alembic downgrade 062` drops the
  Goal tables (count 3 → 0); `alembic upgrade 063` reapplies (0 → 3).
- **Installed-base upgrades, both majors:**
  `tests/migrations/test_goal_installed_base_upgrade.py` — **8 passed**
  (fresh `r60ib18`, pg18) and **8 passed** (fresh `r60ib17`, pg17): databases
  built by the actual merged develop snapshots `c560d4c` (user-model `056`)
  and `4675101` (planner `057`), forward-upgraded to `063` with no stamp edit
  and no reset; merged identities keep meaning and ancestry; facts/keys and a
  representative Run survive; planner indexes and status constraints intact;
  the three Goal tables read back through the durable composition after
  reopen.
- **Migration identity:** `git diff origin/develop..HEAD --
  alembic/versions/056_user_model_facts.py alembic/versions/057_run_store_
  planner_stability.py` is empty (ancestry preserved byte-for-byte);
  `alembic/versions/063_canonical_goals.py` has `revision = "063"`,
  `down_revision = "062"`; single head.
- **Production composition re-read at this head:** `container.py:44` imports
  `wire_goal_store`, `:273` declares `goal_store: GoalStore`, `:276` exposes
  `goal_reader -> ScopedGoalStore`, `:2414`
  `goal_store = await wire_goal_store(db_pool, pg_pool=pg_pool)` inside
  `create_container`; Hive `packages/hive-conductor/backend/adapters/
  maistro_core.py:195` and maistro-server
  `packages/maistro-server/src/maistro_server/main.py:29` compose through
  `create_container`; `test_goal_wiring.py` (inside the 453) proves the
  shipped Container exposes the store.

## Known non-branch local noise (unchanged)

`tests/test_branch_independence_repository.py::
test_every_quality_json_state_surface_is_classified_once` fails in this
worktree only, solely on the untracked, gitignored scratch file
`quality/ac-state.json` (`.gitignore:81`) picked up by the unconditional
rglob in `scripts/check-branch-independence.py:206`. Left untouched; CI
passes this test (its 1 failure is the ledger test above).

## Blocker status (unchanged, external)

The only reds are the execution-lifecycle gate and the shipped-ledger test
that runs it, both on the single missing **already-landed** GoalStatus grant.
Resolution requires a maintainer to land the grant on develop (one entry in
`quality/ratchet-authorizations.json` under `execution-lifecycles`); this
branch then merges cleanly — this round's repair ensures the merge sees a
byte-identical, valid file on the branch side. No code, test, or gate change
is made or needed for that; nothing in this worktree can land it.
