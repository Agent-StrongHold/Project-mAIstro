# #1572 round-93 repair verification (HEAD 09079b573852, dispatch head unchanged)

Dispatch instruction this round: "Previous block (resolve it as part of this round):
worker requested attention: BLOCKED." Resolution attempt executed in full below;
external state re-fetched first-hand and the block re-proven by execution at this
head. **Verdict: BLOCKED — unchanged, and now proven for round 93** on the external
maintainer execution-lifecycles grant: merge grant-only PR #1938 to `develop`, sync
the branch, and the gate + shipped-ledger test pass with **zero branch edits**
(two-merge mechanics, source-verified again this round). Every acceptance criterion
other than the CI gate was re-executed first-hand on a fresh PG container.

## 1. External state re-fetched (not assumed)

- `git fetch origin develop`: tip `3c761d14db94` == merge-base(HEAD, origin/develop)
  == `3c761d14db94`. **UNCHANGED** — no new commits on the integration base.
- `git ls-remote origin refs/pull/1938/head` → `2f5dd46969fc` **UNCHANGED** (unmerged;
  `refs/pull/1938/merge` is a candidate ref, not merge evidence).
- `git grep -c GoalStatus origin/develop -- quality/` → exit 1: **0 grants on develop**.
- `git diff origin/develop...HEAD -- quality/`: only `ac-state-notes/auto-1572.json`,
  `durable-table-retention.json`, `execution-lifecycles.json` (+4, the candidate DOMAIN
  classification at `quality/execution-lifecycles.json:89-92`). The branch carries **no**
  `ratchet-authorizations.json` change — the GoalStatus grant lives only in unmerged
  PR #1938, so an in-branch grant could not help even mechanically (below).

## 2. The failing CI job reproduced at exact CI argv

CI merge-queue evaluation: `test: failure` — sole failed test
`tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code`
(CI log: "1 failed, 4977 passed").

- Gate at exact CI argv (`.github/workflows/quality.yml:1541`,
  `uv run python scripts/check-execution-lifecycles.py`): **EXIT 1**,
  `baseline: base 3c761d14db94`, `19 classified lifecycles -> 20 discovered`,
  sole finding: `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent
  from the trusted base and has no already-landed authorization`.
- Test file re-run: **1 failed, 28 passed**; the failed test's captured stdout is
  byte-identical to the direct gate run (same baseline SHA, same sole finding) —
  the merge-queue `test: failure` is this gate failure, 1:1.

## 3. Why no in-branch repair exists (re-read from source this round)

- `scripts/check-execution-lifecycles.py` `main()`:
  `authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)`;
  `unauthorized = _unauthorized_additions(added, authorized, visible_at_base)` —
  a new identity is authorized **only** by a grant already at the base revision or by
  scanner expansion over base source (`_discover_at_revision`). GoalStatus code does
  not exist at base, so only the base-side grant can admit it.
- `scripts/ratchet_provenance.py:478-503` docstring, verbatim: "a new grant does not
  take effect in the change that introduces it. Authorizing a floor-raise is now
  two merges." `_refuse_self_reference` (:257-270) refuses base==HEAD.
- Therefore any branch built on `3c761d14db94` that introduces the issue-mandated
  GoalStatus lifecycle fails this gate until the grant lands on develop. Removing or
  renaming GoalStatus is prohibited weakening (issue body: goal lifecycle
  active/satisfied/cancelled/failed/superseded, terminal-final, and the candidate
  DOMAIN classification is already in place); hiding the vocabulary from the scanner
  (alias tricks) would defeat the gate the convergence program relies on. **The only
  repair is merging PR #1938 to develop** — a GitHub mutation this lane is prohibited
  from performing.

## 4. Lane-brief vulture CI-repair exception: no amendment target

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` (exact argv, quality.yml:1079-1082): **EXIT 0**,
`1323 reviewed identities -> 1323 findings`, `unclassified: 0`, `never_allowlist: 0`.
The permitted ledger amendment has nothing to amend at this head.

## 5. Acceptance re-executed first-hand (fresh pgvector/pg18 `goals_r93`, port 15493, removed after)

- `DATABASE_URL=...15493/postgres uv run alembic upgrade head` on an empty DB:
  **EXIT 0**, final line `Running upgrade 062 -> 063, The canonical Goal store...`;
  catalog contains exactly `canonical_goals`, `canonical_goal_revisions`,
  `canonical_goal_transitions`.
- Reversibility: `alembic downgrade 062` drops 3→0 canonical_goal% tables;
  re-upgrade to head restores 0→3. EXIT 0 both ways.
- Goals suite: `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=... MAISTRO_TEST_DATABASE_URL=...
  uv run pytest packages/maistro-core/tests/goals -q` → **70 passed, 0 failed, 0 skipped**
  (DSN var names verified in the tests first: `test_goal_store_conformance.py:136-143`,
  `test_goal_pg_schema_agreement.py:38,65-71`).
- No second execution identity: `grep -rn "GoalRun\|OrchestratorRun" packages/*/src`
  → exit 1 (0 hits). Production wiring present: `wire_goal_store` at
  `packages/maistro-core/src/maistro/goals/wiring.py:34`.
- Convergence freeze at exact CI argv (`.github/workflows/formal-conformance.yml:76`):
  `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db94` → **EXIT 0**.
- Docs-only delta proven: `git diff --name-only f8701766034..HEAD` =
  `REPAIR-NOTES-1572-round92.md` only; zero non-docs deltas since the round-89
  battery tree `1f81c113d676`.
- Driver logs green at this head (job dir check-0..4): uv sync resolved/checked,
  `ruff check` "All checks passed!", `ruff format --check` 3288 files, subset pytest
  161 passed / 28 skipped, suite inventory ok (16334 unique identities).
- Local-only environmental failure re-confirmed (not a branch defect; CI passed it):
  `tests/test_branch_independence_repository.py::
  test_every_quality_json_state_surface_is_classified_once` fails in this worktree
  only via the untracked, gitignored `quality/ac-state.json` (`.gitignore:81`)
  found by the checker's unconditional rglob.

## 6. Round conclusion

checked: external state, gate at CI argv, failing test, vulture exception argv,
convergence freeze, migration reversibility, goals suite with PG legs, identity/wiring
greps, docs-only delta, driver logs. done: all re-proven. skipped: none.
errors: 1 (the known, externally-caused gate/test failure).

**Next (maintainer action, outside this lane's permissions):** merge grant-only
PR #1938 (head `2f5dd46969fc`, sole hunk = execution-lifecycles authorization for
`maistro.goals.model::GoalStatus`) into `develop`; then merge origin/develop into
this branch — `check-execution-lifecycles.py` passes because `load_authorizations`
then reads the grant at the new merge-base, and
`test_the_shipped_ledger_matches_the_shipped_code` passes with it. No code, test,
ledger, or grant edits are needed on this branch. No inventory delta (docs-only round).
