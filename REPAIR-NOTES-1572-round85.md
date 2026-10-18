# REPAIR-NOTES #1572 — round 85 (dispatch head bd6a359e6)

Verdict: **BLOCKED** — unchanged, re-proven first-hand this round. The sole CI
failure is the execution-lifecycles floor-raise for
`maistro.goals.model::GoalStatus` (19 → 20 vocabularies), which the repo's
two-merge rule reserves to an already-landed grant on the trusted base. The
grant exists only in unmerged PR #1938; origin/develop has not moved.

## External state re-checked (first-hand, this round)

- `git fetch origin` → `origin/develop` tip `3c761d14db94` == merge-base with
  HEAD. **UNCHANGED** since the last rounds (branch is ~180 commits ahead).
- `git grep GoalStatus origin/develop -- quality/` → exit 1: **zero grants** on
  develop.
- `git ls-remote origin refs/pull/1938/head` → `2f5dd46969fc` (still open,
  unmerged).
- `git diff 3c761d14db94 2f5dd46969fc -- quality/ratchet-authorizations.json`
  contains exactly one new `execution-lifecycles` authorization:
  `maistro.goals.model::GoalStatus`, owner `@BlakeMatthews-dev`, issue `#1572`,
  DOMAIN rationale. (PR #1938's branch carries the whole feature; the grant
  hunk is what matters.)

## The block, re-executed at exact CI argv (quality.yml:1541)

`uv run python scripts/check-execution-lifecycles.py` → **EXIT 1**, sole
finding:

```
- maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the
  trusted base and has no already-landed authorization
```

`uv run pytest tests/test_check_execution_lifecycles.py -q` → **1 failed /
28 passed** (`test_the_shipped_ledger_matches_the_shipped_code`, identical sole
finding) — 1:1 with the merge-queue `test: failure` step. Coverage-combine
failure is inherited from that producer, no independent deficit.

## Two-merge mechanics re-read from source (not assumed)

- `scripts/ratchet_provenance.py:478-503` — `load_authorizations` reads grants
  **from the base revision**; docstring verbatim: "a new grant does not take
  effect in the change that introduces it. Authorizing a floor-raise is now two
  merges."
- `scripts/check-execution-lifecycles.py:773` —
  `prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)`; `:783`
  discovers at `trusted_ref.base_sha`.
- `scripts/ratchet_provenance.py:257-270` — `_refuse_self_reference` refuses
  `RATCHET_BASE_REV=HEAD`.
- `scripts/check-execution-lifecycles.py:704-707` — `_unauthorized_additions`
  blocks candidate self-classification. The candidate DOMAIN classification for
  GoalStatus **is present** (`quality/execution-lifecycles.json:89-92`), so
  classification is not the defect; the missing already-landed grant is.

## No in-branch repair exists (all paths re-examined)

1. **Lane-brief vulture CI-repair exception** (the only permitted ledger edit in
   a repair round): re-run at exact argv (quality.yml:1079-1082)
   `uv run python scripts/check-vulture-baseline.py packages/*/src
   --min-confidence 60 --exclude '*/third_party/*'` → **EXIT 0**, 1323 = 1323,
   unclassified 0, never_allowlist 0. **No amendment target.**
2. In-branch grant in `quality/ratchet-authorizations.json`: structural no-op —
   authorizations are read from the merge base (above). (Round-81 proved this
   by simulation: gate EXIT 0 only when the grant-carrying commit is the
   *ancestor*/base of the measured tree.)
3. Removing/renaming `GoalStatus` violates the issue mandate — the
   active/satisfied/cancelled/failed/superseded lifecycle with terminal-final
   CAS *is* the deliverable (`packages/maistro-core/src/maistro/goals/model.py:52-82`).
4. Weakening the gate or dodging the detector: prohibited.

**Unblock recipe (external maintainer):** merge PR #1938 (or land its grant
hunk) on develop → re-run the merge queue. A merge-group evaluation tests HEAD
merged with the develop tip, whose merge-base (the new develop tip) then
carries the grant; the gate and the shipped-ledger test pass with **zero
branch edits**.

## Acceptance criteria re-executed this round (fresh pgvector/pg18, DB `goals_r85`)

- `uv run alembic upgrade head` (DATABASE_URL → fresh empty pg18 DB) →
  **EXIT 0**, chain empty → 063, single head `063`, final step
  `062 -> 063, The canonical Goal store`. Catalogue contains exactly the three
  goal tables (`canonical_goals`, `canonical_goal_revisions`,
  `canonical_goal_transitions`) beside the pre-existing canonical spine.
- Goals suite with `MAISTRO_REQUIRE_PG_LEGS=1` (PG legs mandatory, not
  silently skipped):
  `MAISTRO_TEST_PG_DSN`/`MAISTRO_TEST_DATABASE_URL` =
  `postgresql://…@127.0.0.1:55485/goals` (**plain** postgresql:// scheme —
  these legs call `asyncpg.create_pool(dsn)` directly; a
  `postgresql+asyncpg://` value errors with "invalid DSN") →
  **70 passed / 0 failed / 0 skipped** (3-backend conformance, CAS one winner,
  stale refusal, terminal-final, subgoal lineage + recorded agent transition,
  two-principals isolation, immutable run binding incl. `test_run_goal_binding`
  on the migrated DB, wiring, schema agreement, restart readback).
- Full migration battery `uv run pytest tests/migrations -q` (both
  `MAISTRO_TEST_DATABASE_URL` and `DATABASE_URL` set) → **168 passed / 0
  skipped / 0 failed**; conftest restored the shared DB to head afterwards.
- Convergence freeze at CI argv (formal-conformance.yml:76-83):
  `uv run python scripts/check-m1-convergence-freeze.py --base
  3c761d14db94…` → **EXIT 0**.
- `git grep 'GoalRun\|OrchestratorRun' -- 'packages/*/src'` → exit 1 (zero
  occurrences; no competing execution identity).
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` →
  3288 files already formatted (driver logs check-1/check-2 concurred).
- `uv run mypy packages/maistro-{core,server,turing,canvas,bootstrap,registry,ext-sdk}/src`
  → Success, 899 source files, no issues.
- Driver logs at this head (job 2ab864bb…): check-0 sync OK, check-1 ruff OK,
  check-2 format OK, check-3 161 passed / 28 skipped, check-4 inventory OK
  (16334 collected = unique).
- Local-only artifact re-confirmed, left untouched:
  `quality/ac-state.json` is untracked and gitignored (`.gitignore:81`);
  `scripts/check-branch-independence.py:206` rglobs `quality/*.json`
  unconditionally, so that one test fails locally only. CI did not see it.

## Round delta

Docs-only (this file). No code, test, or ledger changes; no suite-inventory
delta (no tests added or removed). Worktree left clean at one new commit on
`auto-1572`.
