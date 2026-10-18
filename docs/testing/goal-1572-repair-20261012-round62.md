# Round 62 — deep review of the sole blocker (resolves the NEEDS-DEEP-REVIEW block)

Dispatch head `604760003d87842a1a1e4a05644069733e54901e` (branch `auto-1572`),
base `3c761d14db944a727fa0744444bc67cfe36d49f7` (= `origin/develop`, re-fetched
this round and unchanged; merge-base equals the develop tip). The dispatch head
is docs-only over `db091060d` (`git diff --name-only db091060d..HEAD` lists only
`docs/testing/goal-1572-repair-*.md`), so the code rounds 58–61 validated is the
code at this head; everything below was nevertheless re-executed first-hand in
this round rather than inherited.

## What this round was asked to resolve

The merge-queue evaluation fails exactly one job: `test` (pytest), whose sole
failed step is `tests/test_check_execution_lifecycles.py::
test_the_shipped_ledger_matches_the_shipped_code`; the coverage-combine job
inherits its empty producer. Rounds 59–61 concluded the cause is external (the
two-merge rule) and requested deep review. This round performed that review:
it re-derived the gate's mechanics from source, enumerated and rejected every
in-branch repair, and identified the maintainer-blessed process precedent that
names the required external action.

## The blocker, re-proven first-hand at the dispatch head

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  quality.yml:1541) — **exit 1**, sole finding:
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from
  the trusted base and has no already-landed authorization` (19 → 20).
- `uv run pytest tests/test_check_execution_lifecycles.py -x -q` — **1 failed /
  28 passed**, the failure being `gate.main() != 0` with the same sole finding
  (assertion at tests/test_check_execution_lifecycles.py:374). This is the
  merge-queue `test: failure`.
- `quality/execution-lifecycles.json` diff vs develop: exactly one added
  identity (`maistro.goals.model::GoalStatus`, classified DOMAIN with
  rationale), none removed; the branch ledger is the reviewed classification
  the gate wants — it just cannot self-authorize.
- `git show origin/develop:quality/ratchet-authorizations.json | grep -c
  GoalStatus` — **0 grants**; the last develop commits touching that file do
  not add one.

## Why no in-branch repair exists (derived from source this round)

`scripts/check-execution-lifecycles.py::main` computes
`added = set(found) - set(trusted_entries)` where `trusted_entries` is the
ledger read from the **base revision**
(`ratchet_provenance.resolve_baseline`: precedence explicit arg →
`RATCHET_BASE_REV` → GitHub event base → `origin/develop`; the worktree
fallback fires only when no base resolves at all, and `_refuse_self_reference`
rejects a base equal to HEAD). An addition passes only if it is in
`authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)` —
grants read from the **base revision's** `quality/ratchet-authorizations.json`
— or in `visible_at_base = _discover_at_revision(base_sha, found)` — the
detector re-run over the base's source, impossible for a module
(`maistro/goals/`) that does not exist anywhere at the base. Every in-branch
path is therefore closed:

1. **In-branch grant or candidate-ledger edit** — structurally invisible to the
   gate (base-read), and empirically a no-op (round 59's grant commit
   `2f5dd4696` still failed).
2. **Removing or renaming the `GoalStatus` vocabulary** — the issue's scope
   mandates the lifecycle (`Goal lifecycle: e.g. active, satisfied, cancelled,
   failed, superseded. Transitions are compare-and-set on revision and state.
   Terminal states are final.`); renaming members to fall below the detector's
   three-work-state threshold would misrepresent a genuine work-state
   vocabulary to dodge discovery, i.e. weaken the gate (prohibited).
3. **Editing the gate or provenance loader** — gate weakening (prohibited).
4. **`RATCHET_BASE_REV` override** — self-authorization; CI never sets it.
5. **The lane brief's vulture-ledger amendment exception** — no target:
   `uv run python scripts/check-vulture-baseline.py packages/*/src
   --min-confidence 60 --exclude '*/third_party/*'` (exact CI argv,
   quality.yml:1079) — **exit 0**, 1323 reviewed = 1323 findings,
   unclassified 0. Nothing to amend in `quality/vulture-baseline.json`.

## Process precedent (from the #1572 comment snapshot, 2026-10-03)

BlakeMatthews-dev (MEMBER) hit the identical situation for this branch's
**vulture** debt: "#1572's code introduces 7 new Vulture findings … that the
trusted-base ratchet correctly refuses to let the same PR self-authorize.
Grant PR: #1833 — once that merges to develop, this branch merges develop".
#1833 merged (develop commit `d7f7f6f81`, "authorize the canonical Goal
store's new vulture identities"). The GoalStatus execution-lifecycles grant
needs exactly the same treatment. Searched all 74 open PRs in the dispatch
snapshot: only #1855/#1938 (the feature PRs themselves) mention GoalStatus;
**no grant PR for it exists**.

## Required external action (unchanged, now with precedent named)

A maintainer lands one grant entry in `quality/ratchet-authorizations.json`
under `execution-lifecycles` for `maistro.goals.model::GoalStatus` **on
develop** (grant PR per the #1833 precedent). This branch then merges
`origin/develop` and the gate and the shipped-ledger test pass with zero
branch edits — the branch's DOMAIN classification and rationale are already
in place. Nothing in this worktree can land that grant (no-push/no-GitHub-
mutation constraints), which is why the branch is blocked, not repairable.

## Acceptance evidence re-executed first-hand this round (dispatch head)

Driver logs (job dir): ruff check "All checks passed", format "3288 files
already formatted", 9-file set 161 passed/28 skipped, suite inventory ok
(16334 = 16334, 0 duplicates). Re-run first-hand here:

- `uv run ruff check .` — pass; `uv run ruff format --check .` — 3288 files clean.
- `uv run mypy packages/maistro-core/src … packages/maistro-ext-sdk/src` —
  **Success: no issues found in 899 source files**.
- `check-m1-convergence-freeze.py --base 3c761d14db94…` (formal-conformance
  yml:77 argv) — **exit 0**: no `GoalRun`, no second executor, no
  product-private Goal lifecycle.
- **Fresh migrations, both majors:** lane containers `auto-1572-pg` (pg18,
  :55712) / `auto-1572-pg17` (pg17, :55717); fresh databases `r62g18` /
  `r62g17` migrated empty → head, final line `062 -> 063, The canonical Goal
  store`; `alembic heads`/`current` = single head 063; all three
  `canonical_goal*` tables present on both majors.
- **Goals + events with PG legs forced** (`MAISTRO_REQUIRE_PG_LEGS=1`,
  `MAISTRO_TEST_PG_DSN` + `MAISTRO_TEST_DATABASE_URL` at `r62g18`) —
  **453 passed, 0 skipped**: conformance across memory/sqlite/postgres,
  append-only revisions with CAS (exactly one concurrent winner), stale
  revision refused, subgoal lineage preserving parent Goal and Project,
  foreign Goal == missing Goal, immutable `goal_id`/`goal_revision` Run
  binding (`test_run_goal_binding.py` 11/11 incl. postgres legs and
  `test_a_run_outcome_never_moves_goal_state`), Workspace isolation, PG
  schema agreement, restart readback
  (`test_goal_revisions_and_bound_run_provenance_survive_a_restart`), shipped
  Container wiring (`test_goal_wiring.py`).
- **Goals-only at `r62g17`** (second supported major) — **70 passed, 0 skipped**.
- **Downgrade/reapplication** on `r62g18`: `alembic downgrade 062` drops the
  Goal tables (3 → 0); `alembic upgrade head` reapplies (0 → 3).
- **Installed-base upgrades, both majors:**
  `tests/migrations/test_goal_installed_base_upgrade.py` — **8 passed**
  (fresh `r62ib18`, pg18) and **8 passed** (fresh `r62ib17`, pg17): databases
  built by the actual merged develop snapshots `c560d4c` (user-model `056`)
  and `4675101` (planner `057`), forward-upgraded to `063` with no stamp edit
  and no reset; merged identities keep meaning and ancestry (056/057 files
  byte-identical to develop; the only `alembic/versions/043_*` delta vs
  develop is its docstring); facts/keys and a representative Run survive;
  planner indexes and status CHECK intact; Goal tables read back through the
  durable composition after reopen.
- **Production composition re-read at this head:** `container.py:44` imports
  `wire_goal_store`, `:273` declares `goal_store`, `:276` exposes
  `goal_reader -> ScopedGoalStore`, `:2412-2414` wires the store inside
  `create_container`; Hive `packages/hive-conductor/backend/adapters/
  maistro_core.py:195` and maistro-server
  `packages/maistro-server/src/maistro_server/main.py:29` compose through
  `create_container`. Workflow deltas vs develop are additive test
  registrations only (ci.yml adds the goals PG-legs step; quality.yml adds
  `packages/maistro-core/tests/goals` to the coverage producer set).

## Known non-branch local noise (unchanged)

`tests/test_branch_independence_repository.py::
test_every_quality_json_state_surface_is_classified_once` fails in this
worktree only, solely on the untracked, gitignored scratch file
`quality/ac-state.json` (`.gitignore:81`) picked up by the unconditional
rglob in `scripts/check-branch-independence.py:206`. Left untouched; CI
passes it (its 1 failure is the ledger test above).

## Verdict rationale

All issue acceptance criteria are implemented and proven by executed tests at
this head; the only reds are the execution-lifecycle gate and the
shipped-ledger test that runs it, both on the single missing **already-landed**
GoalStatus grant — a structural two-merge requirement with an explicit
maintainer process precedent (#1833), not a branch defect. No in-branch repair
exists; the lane-brief vulture amendment exception has no target. Blocked on
that external grant, after which the branch merges develop and passes with
zero further edits. No code, test, or ledger changes were made this round; no
tests added, no inventory delta.
