# #1572 repair round 6 — independent re-verification at c7aed677d; sole red confirmed external

Round lane: `auto-1572` @ `c7aed677d222` (clean tree, no source change this
round). Prior round's attempt died on a provider timeout after its driver
checks had already passed; this round re-proves the state first-hand rather
than trusting that transcript, and re-evaluates the one open red.

## The named CI gate failures, re-run at this head

- **`test` (merge-queue red): reproduced; cause is exactly the documented
  external grant.** `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-execution-lifecycles.py` (quality.yml:1520's exact argv) →
  FAIL with a single finding: `maistro.goals.model::GoalStatus: NEW work-state
  vocabulary is absent from the trusted base and has no already-landed
  authorization`. The root-suite self-check that reds the `test` job,
  `tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_
  the_shipped_code`, fails on that same sole finding (28 other tests in the
  file pass). The candidate ledger classifies GoalStatus as DOMAIN with a
  rationale; the ratchet deliberately refuses same-change self-approval and
  reads authorizations from the merge base `cc6e4899ddef`, where
  `quality/ratchet-authorizations.json` has no `execution-lifecycles` row for
  it, and `maistro/goals/` does not exist in the base source (so it cannot
  count as newly visible). Closing it requires an authorization landed on
  develop first (the documented two-merge rule) — outside this lane's
  prohibitions against pushing and PR creation. `origin/develop` was fetched
  and is unchanged at `ed5613457` (the lane base): there is no grant to merge
  and no sync conflict to resolve.
- **Quality gate: everything but the item above is green first-hand.**
  `check-ac-state.py --run-tests --ratchet --mandate cc6e4899ddef498044c…`
  (quality.yml's exact argv, PG 18 live) → EXIT 0 — the round-5 banking in
  `quality/ac-state-notes/auto-1572.json` holds; mandate and chain both clean.
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (lane-brief argv) → EXIT 0, 1323 reviewed identities →
  1323 findings, 0 unclassified. `check-m1-convergence-freeze.py --base
  cc6e4899ddef` → EXIT 0 ("no unapproved new architecture island").
- **Coverage gate: the round-5 fix verified at the test and inventory level.**
  `uv run pytest tests/test_verify_wheel_imports.py -q` → 23 passed (includes
  the five `TestTheSiblingConstraintPin` node IDs added by c7aed677d to cover
  the sibling-wheel `--constraints` pinning that the diff gate had flagged at
  20%); `check-suite-inventory.py --suite 'tests/'` → EXIT 0, 5185 collected
  node IDs matching the recorded baseline (+5); the note
  `docs/testing/inventory-notes/1572-wheel-sibling-constraint-pinning.md`
  carries the required `inventory-delta:` block. The full coverage producers
  were not re-executed this round; the publish-set/diff evidence at this exact
  head is round 5's (nothing has changed since — c7aed677d is that round's
  commit and the tree is clean at it).

## Issue acceptance legs re-proven first-hand (pgvector/pg18, PostgreSQL 18.6, chain applied to `062 (head)`)

- `alembic upgrade head` on a fresh database applied the whole chain,
  ending `062 (head)`, with the merged `056` (user-model) and `057`
  (planner-stability) identities applied in their merged meaning and
  ancestry; the Goal migration appends as `062` — no identity reuse.
- Goals suite with PG legs forced
  (`MAISTRO_REQUIRE_PG_LEGS=1`, `MAISTRO_TEST_PG_DSN`,
  `MAISTRO_TEST_DATABASE_URL`): **70 passed, 0 skipped** — three-backend
  conformance (round-trip, append-only revisions, stale-revision refusal,
  single CAS winner, subgoal lineage preserving parent/Project, agent
  reassignment as a recorded transition, two principals in two Workspaces
  isolated, foreign Goal ≡ missing Goal), Run binding (admission binds
  `goal_id`/`goal_revision`, immutable after admission), restart readback,
  Container wiring (including PostgreSQL wiring over a migrated pool and the
  bare-database schema bring-up), and migration-062 ↔ ensure-schema agreement.
- `tests/migrations` on the same live server: **165 passed** — including the
  eight installed-base upgrade tests that build populated fixtures from the
  actual pre-Goal develop snapshots (`c560d4c` through user-model `056`,
  `4675101` through planner `057`, HITL `061`) and forward-upgrade without
  restamping, plus fresh-install, single-head, downgrade/refusal and
  reapplication coverage.

## Verdict of this round

Everything this lane can establish is green and re-proven at the exact head.
The single remaining red — the GoalStatus execution-lifecycle authorization —
is a develop-side prerequisite by the repository's own two-merge design; no
in-branch change can close it without either self-authorizing (forbidden and
mechanically ineffective) or weakening the scanner (forbidden). The lane is
BLOCKED on that external prerequisite: land an
`execution-lifecycles` authorization for
`maistro.goals.model::GoalStatus` on develop (or admit the classification
there), then re-cut or re-merge this branch so the merge base carries it.
