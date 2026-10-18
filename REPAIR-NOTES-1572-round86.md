# REPAIR NOTES #1572 — round 86 (dispatch head aa144237d88b)

Scope: repair lane for issue #1572 (canonical Goal store, `maistro.goals`).
Prior verdict: BLOCKED (rounds 74–85) on the external maintainer execution-lifecycles
grant for `maistro.goals.model::GoalStatus`, carried by unmerged grant-only PR #1938.
This round: external state re-checked, block re-proven at exact CI argv, every crux
claim re-derived from source (none assumed), acceptance legs re-executed on a fresh
migrated database. **No code, test, or ledger changes; docs-only.**

## External state (checked first, unchanged)

- `git fetch origin` → tip `origin/develop` = `3c761d14db94` = `git merge-base origin/develop HEAD`
  (branch 187 ahead; **nothing to sync**).
- `git grep GoalStatus origin/develop -- quality/` → exit 1: **0 grants on develop**.
- `git ls-remote origin refs/pull/1938/head` → `2f5dd46969fc` **UNCHANGED** (still open/unmerged;
  the `refs/pull/1938/merge` ref exists for any open PR and is not merge evidence). Head unchanged
  ⇒ the grant hunk content verified in round 74/81 from that exact SHA still applies: exactly one
  execution-lifecycles entry for `maistro.goals.model::GoalStatus` (owner @BlakeMatthews-dev, issue #1572).

## The block, re-proven at CI's exact argv (quality.yml:1541)

`uv run python scripts/check-execution-lifecycles.py` → **EXIT 1**, sole finding:

```
maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the trusted base
and has no already-landed authorization   (19 -> 20)
```

`uv run pytest tests/test_check_execution_lifecycles.py -q` → **1 failed, 28 passed**;
`test_the_shipped_ledger_matches_the_shipped_code` fails with the identical sole finding
(gate-identical stdout) = the merge-queue `test: failure` 1:1; the coverage `combine` step
inherits from this failed producer (no independent floor/diff-coverage deficit).

## Why no in-branch repair exists — re-derived from source this round

1. **Grants are read from the base revision** — `scripts/ratchet_provenance.py:478-503`,
   `load_authorizations(RATCHET, base=trusted_ref.base_sha)` called from the gate
   (`check-execution-lifecycles.py:773`); the docstring states the two-merge rule verbatim:
   "a new grant does not take effect in the change that introduces it … two merges".
2. **Self-authorization via base override is refused** — `_refuse_self_reference`
   (`ratchet_provenance.py:257-270`) raises `SelfReferentialBaseline` for `RATCHET_BASE_REV=HEAD`.
3. **Candidate self-classification is non-authorizing** — `_unauthorized_additions`
   (`check-execution-lifecycles.py:704-707`) drops candidate-ledger classifications when
   deciding what is newly added; the candidate DOMAIN entry for `maistro.goals.model::GoalStatus`
   **is present** in `quality/execution-lifecycles.json` (with the full desired-state rationale),
   so classification is not the defect.
4. **An in-branch grant is a structural no-op** — `git diff origin/develop -- quality/ratchet-authorizations.json`
   = **0 lines** (byte-identical; the in-branch grant from 2f5dd4696 was removed by 8510776ae+826cd0879).
   Even re-adding it could not authorize (see 1).
5. **Removing/renaming GoalStatus is not a repair** — `packages/maistro-core/src/maistro/goals/model.py:52-72`
   ships the issue-mandated lifecycle `ACTIVE` + terminal `SATISFIED/CANCELLED/FAILED/SUPERSEDED`
   with `TERMINAL_GOAL_STATUSES`; dodging the detector would be prohibited gate weakening.
6. **The lane-brief vulture exception has no target** — `uv run python scripts/check-vulture-baseline.py
   packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (exact CI argv, quality.yml:1079-1082)
   → **EXIT 0**, `1323 reviewed identities -> 1323 findings`, unclassified 0, never_allowlist 0.
   The failing gate is execution-lifecycles, not vulture; there is nothing to amend.

## Acceptance legs re-executed this round (fresh evidence, not carried over)

- **Fresh migrated DB `goals_r86`** (fresh database in the healthy `maistro-postgres` pgvector/pg18
  container, port 5433): `DATABASE_URL=postgresql://…goals_r86 uv run alembic upgrade head` from empty →
  **EXIT 0**, single head, final step `062 -> 063, The canonical Goal store`; `\dt` shows exactly
  `canonical_goals`, `canonical_goal_revisions`, `canonical_goal_transitions` alongside the spine.
- **Goals suite with PG legs required** (`MAISTRO_TEST_PG_DSN` + `MAISTRO_TEST_DATABASE_URL` +
  `MAISTRO_REQUIRE_PG_LEGS=1`, plain `postgresql://` DSNs — these legs call asyncpg directly):
  **70 passed, 0 failed, 0 skipped** (3-backend conformance, CAS one-winner, stale refusal,
  terminal-final, subgoal lineage, recorded agent transition, two-principals isolation,
  immutable run binding, schema agreement, restart readback, Container wiring).
- **Convergence matrix at the true CI argv** (quality.yml:1377, no args): **EXIT 0** —
  "52 subsystems classify all 1401 production modules; 169 unreachable modules are attributed".
  *Correction to round ≤85 records: `scripts/check-convergence-matrix.py` accepts only `[--census]`;
  the previously cited `--base 3c761d14db94` argv is not part of its CLI (harmless: plain argv passes).*
- **Single execution spine**: `grep -rn 'GoalRun|OrchestratorRun' packages/*/src` → exit 1 (absent).
- **Production composition, source-read**: `container.py:44` imports `wire_goal_store`;
  `:271-276` the `goal_reader` ScopedGoalStore seam; `:2412-2414` `wire_goal_store(db_pool, pg_pool=pg_pool)`
  inside `create_container`.
- **mypy**: 899 source files, no issues. **ruff check / format**: green at this head
  (driver logs check-1/check-2: "All checks passed!", "3288 files already formatted").
- **Driver targeted suite** (check-3): 161 passed, 28 skipped; **suite inventory** (check-4):
  16334 = 16334, 0 duplicates, ok.

## Known local-only artifact (not a branch defect, untouched)

`quality/ac-state.json` is untracked and gitignored (`.gitignore:81`) in this worktree;
`scripts/check-branch-independence.py:206` rglobs it unconditionally, so
`tests/test_branch_independence_repository.py` fails here only. CI passed that test. Left untouched.

## Verdict

**BLOCKED** — unchanged, on one external dependency: the execution-lifecycles grant for
`maistro.goals.model::GoalStatus` must land on `origin/develop` (merge grant-only PR #1938,
or a grant-first PR with the same single entry). Rounds 74/77/81 demonstrated by execution
(develop+grant simulation → gate EXIT 0 "authorized: maistro.goals.model::GoalStatus", shipped-ledger
test 29/29) that once the grant lands, this branch passes gate + test **with zero branch edits**.
All issue acceptance criteria are green first-hand; the only red is the two-merge deadlock that
no in-branch change can resolve without violating the no-weakening and no-ledger rules.
