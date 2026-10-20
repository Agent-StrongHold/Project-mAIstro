# REPAIR NOTES — issue #1572, round 95 (job 559a8ccd0cad4490885b663d4619340c)

Dispatch head `1e2e52be69fff5c6c8aeac57182002bad9abd7cd` (clean worktree, matches
the assigned starting head exactly). Driver logs in the job directory are green:
uv sync resolved/checked 256/214 packages (check-0.log), `ruff check` "All checks
passed!" (check-1.log), `ruff format --check` 3288 files (check-2.log), subset
pytest **161 passed / 28 skipped** (check-3.log), suite inventory **ok (16334
unique identities)** (check-4.log). The lane brief repeats the standing block
("worker requested attention: BLOCKED") and offers a vulture-ledger CI-repair
exception; this round re-proved the block by execution, re-checked every
external input, and re-executed the acceptance battery on a fresh PG container.
Nothing below is carried over on trust.

## 1. External state re-fetched first-hand (2026-10-13, this round)

- `git fetch origin develop` → `git rev-parse origin/develop` =
  **3c761d14db944a727fa0744444bc67cfe36d49f7**, and
  `git merge-base HEAD origin/develop` = the same SHA: **develop is unchanged**
  and is still exactly the merge base of this branch.
- `git grep GoalStatus origin/develop -- quality/` → **0 matches (no grants)**:
  develop carries no execution-lifecycles authorization for
  `maistro.goals.model::GoalStatus`.
- `git ls-remote origin refs/pull/1938/head` → **2f5dd46969fc38b23502d5e40ef35d1f0879ba14**,
  **unchanged**: the grant-only PR #1938 is still open/unmerged. (Had it
  merged, develop would have advanced past 3c761d14db94; it has not.)
- `git diff --numstat origin/develop..HEAD -- quality/` → only
  `quality/ac-state-notes/auto-1572.json`, `quality/durable-table-retention.json`,
  `quality/execution-lifecycles.json` (+4 lines = the DOMAIN classification row
  for GoalStatus). **No `ratchet-authorizations.json` row on this branch** — the
  grant lives only in PR #1938, as an in-branch grant is a structural no-op
  (§3).

## 2. The block, re-proven by execution at this head

- `uv run python scripts/check-execution-lifecycles.py` — the exact CI argv
  (quality.yml:1541) — **EXIT 1**, sole finding:
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the
  trusted base and has no already-landed authorization` (19 classified → 20
  discovered; baseline base 3c761d14db94, candidate 1e2e52be69ff).
- `uv run pytest tests/test_check_execution_lifecycles.py -q` → **1 failed /
  28 passed**; the one failure is
  `test_the_shipped_ledger_matches_the_shipped_code`, whose captured stdout is
  byte-identical to the direct gate run above and whose assertion is
  `main() == 0` (tests/test_check_execution_lifecycles.py:374). This is the
  merge-queue `test: failure` reproduced 1:1.

## 3. Two-merge mechanics re-read from source (not assumed)

- scripts/check-execution-lifecycles.py:773 —
  `authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)`:
  grants are read **from the merge base**, never from the candidate.
- :705–709 `_unauthorized_additions` admits a newly discovered identity only if
  it is base-side-authorized **or** `visible_at_base`; :783–784 compute both.
  New code (`GoalStatus`) is by definition not visible at base, so only a
  base-side grant can admit it.
- scripts/ratchet_provenance.py:478–503, docstring verbatim: *"a new grant does
  not take effect in the change that introduces it. Authorizing a floor-raise is
  now two merges."* `_refuse_self_reference` (:257–270) closes the degenerate
  base==HEAD path. **Conclusion: no in-branch edit can authorize GoalStatus.**

## 4. Weakening ruled out — the vocabulary is issue-mandated

- Issue body re-read verbatim from dispatch-context.json:
  *"**Goal lifecycle:** e.g. active, satisfied, cancelled, failed, superseded.
  Transitions are compare-and-set on revision and state. Terminal states are
  final. A Run's outcome never sets Goal state implicitly."* and the checklist
  item *"No `GoalRun`, `OrchestratorRun`, second executor or product-private
  Goal lifecycle is introduced (`check-m1-convergence-freeze.py`)."*
- packages/maistro-core/src/maistro/goals/model.py — `GoalStatus` is exactly
  ACTIVE/SATISFIED/CANCELLED/FAILED/SUPERSEDED with `TERMINAL_GOAL_STATUSES`
  enforced. Removing, renaming, or hiding it to satisfy the gate would weaken an
  acceptance criterion; the DOMAIN classification row already exists on this
  branch (quality/execution-lifecycles.json, +4 lines), so classification is not
  the defect. The sole resolution is the maintainer-side grant landing in
  develop (merge grant-only PR #1938), after which the branch passes gate+test
  with zero branch edits.

## 5. Lane-brief vulture CI-repair: no amendment target

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (quality.yml:1079–1082 argv)
  → **EXIT 0**, `1323 reviewed identities -> 1323 findings`, unclassified 0,
  never_allowlist 0. `quality/vulture-baseline.json` needs **no amendment**; the
  failing gate is execution-lifecycles, which the exception does not cover.

## 6. Acceptance battery re-executed first-hand (fresh pgvector:pg18
`goals_r95`, port 15495; container removed after)

- `uv run alembic upgrade head` (DATABASE_URL to the empty container) →
  **EXIT 0**, last line `062 -> 063, The canonical Goal store:
  canonical_goals and its append-only children`; catalogue contains exactly
  `canonical_goals`, `canonical_goal_revisions`, `canonical_goal_transitions`
  (75 tables total).
- `uv run alembic downgrade 062` → **EXIT 0**, canonical_goal% tables 3 → 0;
  re-`upgrade head` → **EXIT 0**, 0 → 3. Round-trip clean.
- `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=… MAISTRO_TEST_DATABASE_URL=…
  uv run pytest packages/maistro-core/tests/goals -q` → **70 passed / 0 failed /
  0 skipped** (env var names verified in test sources first:
  test_goal_pg_schema_agreement.py:38/:65, test_goal_store_conformance.py:31).
- `uv run python scripts/check-m1-convergence-freeze.py --base
  3c761d14db944a727fa0744444bc67cfe36d49f7` (formal-conformance.yml:70–77 argv)
  → **EXIT 0**, "no unapproved new architecture island".
- `grep -rn "GoalRun\|OrchestratorRun" packages/*/src/` → **exit 1 (absent)**.
- Production wiring source-read: packages/maistro-core/src/maistro/container.py
  :42–44 imports `wire_goal_store`/`GoalStore`/`ScopedGoalStore`, :268–277 the
  `goal_store` field and `goal_reader` seam; goals/wiring.py `wire_goal_store`
  selects PgGoalStore (with `ensure_goal_schema`) / SqliteGoalStore / memory.

## 7. Scope identity of the code tree

- `git diff --name-only 1f81c113d676..HEAD` → only REPAIR-NOTES round-89…94
  files (647 insertions, zero non-notes files): the code tree is byte-identical
  to the tree on which rounds 89–94 ran the full battery, and this round re-ran
  the battery anyway (§6).
- Local-only, environmental, not a branch defect: untracked, gitignored
  `quality/ac-state.json` (`.gitignore:81`) is the sole trigger of the local
  branch-independence check failure; `git status --porcelain quality/` is empty,
  so CI never sees it.

## Verdict

**BLOCKED** — unchanged, and only resolvable outside this branch: the grant-only
PR #1938 (single hunk: execution-lifecycles authorization for
`maistro.goals.model::GoalStatus`, owner BlakeMatthews-dev, issue #1572) must be
merged to develop by the maintainer; the branch then syncs and the gate, the
shipped-ledger test, and the merge queue pass with zero branch edits (executed
simulations rounds 74/77/81). In-branch alternatives are exhausted: an in-branch
grant is read from the base and is a no-op (§3); removing/renaming the mandated
vocabulary is prohibited weakening (§4); the vulture ledger has no unbanked
identity to amend (§5). This round changed docs only (this notes file); no code,
test, or ledger changes; no inventory delta.
