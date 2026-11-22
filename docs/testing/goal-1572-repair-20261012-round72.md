# #1572 repair verification — round 72 (2026-10-12)

Dispatch head `e981c1b84086fc6d9430f54b8df65881d2c1665a`, base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
Job `357b2216ffad45f2865047213fd58229`. Every claim below was re-executed first-hand this round;
nothing is carried over from earlier rounds. The tree is code-identical to the round-71 dispatch
head (`git diff 7b5801bc7644..HEAD` = the round-71 note file only), so driver checks recorded at
this head apply to this exact code.

## Blocker re-proven (unchanged, external)

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv, `quality.yml:1541`) →
  **exit 1**, sole finding: `maistro.models.goals…`/`maistro.goals.model::GoalStatus: NEW
  work-state vocabulary is absent from the trusted base and has no already-landed authorization`
  (19 → 20).
- `uv run pytest tests/test_check_execution_lifecycles.py -q` → **1 failed, 28 passed**;
  `test_the_shipped_ledger_matches_the_shipped_code` runs the gate's `main()` and its captured
  stdout is identical to the gate run above. This is the merge-queue `test: failure`; the
  coverage `combine` step inherits the dead root-suite producer.
- `git fetch origin` re-run: `origin/develop` tip == merge-base `3c761d14db94`, **0 behind** →
  nothing to merge, no sync conflict, and the grant has not landed.
- `git grep GoalStatus origin/develop -- quality/` → no matches (develop's execution-lifecycles
  authorizations remain exactly RunStatus + DelegationStatus, #1136).
- Two-merge mechanism re-read from source this round: `scripts/ratchet_provenance.py:478`
  `load_authorizations(..., base)` reads grants **from the base revision**; its docstring states
  verbatim: "a new grant does not take effect in the change that introduces it. Authorizing a
  floor-raise is now two merges -- the grant, then the regression it permits". The gate consumes
  this at `scripts/check-execution-lifecycles.py:773` (`load_authorizations(RATCHET,
  base=trusted_ref.base_sha)`) plus base-visibility at `:783`.
- `git cat-file -e 3c761d14db94:packages/maistro-core/src/maistro/goals/model.py` → exit 128:
  the module does not exist at base, so base-visibility can never admit GoalStatus for this
  branch, and an in-branch grant is a proven no-op.
- Candidate ledger already classifies `maistro.goals.model::GoalStatus` as DOMAIN with rationale
  (`quality/execution-lifecycles.json`) — demonstrated live this round: the DOMAIN entry is
  present and the gate still fails, i.e. self-classification does not authorize by design.
- No in-branch repair exists without violating protocol or scope: in-branch grant = no-op (above);
  removing/renaming GoalStatus (ACTIVE/SATISFIED/CANCELLED/FAILED/SUPERSEDED) abandons the
  issue-mandated lifecycle ("Goal lifecycle: e.g. active, satisfied, cancelled, failed,
  superseded") or dodges the work-state detector (gate weakening, prohibited). Resolution is the
  external maintainer execution-lifecycles grant for `maistro.goals.model::GoalStatus` on
  develop (grant-only PR #1938 is that shape; #1833 is the landed two-merge precedent), then this
  branch merges develop; gate + test pass with zero further edits.

## Lane-brief vulture CI-repair exception: no target

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (exact argv, `quality.yml:1079`) → **exit 0**, 1323 reviewed →
  1323 findings, `unclassified: 0`. Nothing to amend in `quality/vulture-baseline.json`.

## Acceptance legs re-executed first-hand (fresh pg18 databases)

- Fresh DB `r72g18` on the running pg18 container: `alembic upgrade head` from empty → **063,
  single head**, final step `062 -> 063, The canonical Goal store`; `canonical_goals`,
  `canonical_goal_revisions`, `canonical_goal_transitions` all present.
- `uv run pytest packages/maistro-core/tests/goals -q` with `MAISTRO_REQUIRE_PG_LEGS=1` and both
  DSNs pointed at `r72g18` → **70 passed, 0 failed, 0 skipped** (3-backend conformance including
  the PostgreSQL leg, append-only CAS single-winner + stale refusal, subgoal lineage, immutable
  Run binding, PG schema agreement, restart readback, Container wiring).
- `MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest tests/migrations -q` against fresh `r72chain` →
  **168 passed** (chain integrity incl. the Goal migration and its downgrade paths).
- `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db94…` (CI argv,
  `formal-conformance.yml:77`) → **exit 0**: no unapproved new architecture island (no GoalRun /
  second executor).
- Driver checks green at this exact head (`check-0..4.log`): `uv sync --locked --extra dev`,
  `ruff check .`, `ruff format --check .` (3288 files), focused 9-file suite **161 passed,
  28 skipped**, suite inventory **ok (16334 = 16334, 0 duplicates)**.
- `quality/ac-state.json` remains an untracked, gitignored (`.gitignore:81`) local scratch file;
  left untouched (the local-only branch-independence false positive it causes is not a branch
  defect).

## Verdict

**BLOCKED** — unchanged and re-proven first-hand. The only failing CI signal traces to the
execution-lifecycles two-merge rule; the required authorization for
`maistro.goals.model::GoalStatus` must land on `origin/develop` first (maintainer action), after
which this branch merges develop and every gate passes with zero edits. No code, test, or ledger
changes were made this round; no inventory delta.
