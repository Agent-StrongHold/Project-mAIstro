# REPAIR NOTES — issue #1572, round 94 (job e4da3ac154d645e39ea421d4c9e835c3)

Dispatch head `f182680be791748a16995f7eb021043f5c806614` (unchanged worktree, clean).
Driver logs in the job directory are green: uv sync resolved/checked 256/214
packages, `ruff check` "All checks passed!", `ruff format --check` 3288 files,
subset pytest **161 passed / 28 skipped**, suite inventory **ok (16334 unique
identities)**. Dispatch asked this round to resolve the standing BLOCKED; every
external input was re-fetched first-hand and the block persists unchanged, so
this round re-proves the block by execution and re-executes every acceptance
criterion fresh. Nothing below is carried over on trust.

## 1. External state re-fetched first-hand (2026-10-13, this round)

- `git fetch origin` then `git rev-parse origin/develop` → **3c761d14db94…**
  (`refs/heads/develop` via ls-remote matches) — **unchanged**, still the
  merge-base of this branch. `git merge-base HEAD origin/develop` =
  3c761d14db94.
- `git grep -c GoalStatus origin/develop -- quality/` → **0 matches (exit 1)**:
  develop carries **no** execution-lifecycles grant for
  `maistro.goals.model::GoalStatus`.
- `git ls-remote origin refs/pull/1938/head` → **2f5dd46969fc…, still open**
  (unmerged; develop's 0 grants proves it definitively). `refs/pull/1855/head`
  → 3f2c79a70d9e (the implementation PR, also open).
- Branch `quality/` numstat vs develop: `ac-state-notes/auto-1572.json` (+17),
  `durable-table-retention.json` (+39), `execution-lifecycles.json` (+4).
  **No `ratchet-authorizations.json` row** — the grant lives only in unmerged
  PR #1938; an in-branch grant would be a structural no-op anyway (§3).

## 2. The named CI failure re-proven at exact argv

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  `.github/workflows/quality.yml:1541`): **EXIT 1**, sole finding
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from
  the trusted base and has no already-landed authorization` (19 → 20
  vocabularies; baseline base 3c761d14db94, candidate f182680be791).
- `uv run pytest tests/test_check_execution_lifecycles.py -q` → **1 failed,
  28 passed**; the failed test is
  `test_the_shipped_ledger_matches_the_shipped_code`
  (asserts `gate.main() == 0`, tests/test_check_execution_lifecycles.py:374)
  and its captured stdout is identical to the direct gate run above —
  1:1 with the merge-queue `test: failure`. The coverage-combine job inherits
  from this failed producer.
- The candidate DOMAIN classification **is present** at
  `quality/execution-lifecycles.json:89-92` with a full rationale, so
  classification is not the defect; the gate requires an
  **already-landed** authorization.

## 3. No in-branch repair exists (re-derived from source, not carried over)

- `scripts/ratchet_provenance.py:478-503` — `load_authorizations` reads grants
  **from the base revision** (`resolve_baseline(path, base=base)`); docstring
  verbatim: "a new grant does not take effect in the change that introduces it.
  Authorizing a floor-raise is now two merges".
- `scripts/check-execution-lifecycles.py:773` —
  `authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)`;
  `:704-707` `_unauthorized_additions` spares an added identity only if it is
  granted **at base** or `visible_at_base` (scanner finds it in the trusted
  source at base — impossible for code introduced by this change).
- `scripts/ratchet_provenance.py:257-270` `_refuse_self_reference` — pointing
  the baseline at HEAD is refused.
- The issue body mandates the vocabulary verbatim: "**Goal lifecycle:** e.g.
  active, satisfied, cancelled, failed, superseded. Transitions are
  compare-and-set on revision and state. Terminal states are final." and the
  acceptance list forbids "No `GoalRun`, `OrchestratorRun`, second executor or
  product-private Goal lifecycle" — removing/renaming/hiding `GoalStatus`
  would weaken a mandated criterion and defeat the convergence detector.
- Lane-brief vulture CI-repair exception re-run at exact argv
  (quality.yml:1079-1082): `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → **EXIT 0**,
  `1323 reviewed identities -> 1323 findings`, `unclassified: 0`,
  `never_allowlist: 0` — **no amendment target** in the vulture ledger either.

**Conclusion: the only repair is merging grant-only PR #1938 to develop** —
a GitHub mutation this lane is prohibited from performing.

## 4. Acceptance re-executed first-hand (fresh pgvector/pg18 `goals_r94`, port 15494, removed after)

- `DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:15494/postgres
  uv run alembic upgrade head` on an empty DB: **EXIT 0**, final line
  `Running upgrade 062 -> 063, The canonical Goal store...`; catalog contains
  exactly `canonical_goals`, `canonical_goal_revisions`,
  `canonical_goal_transitions`; `alembic_version` = `063`.
- Reversibility: `alembic downgrade 062` → canonical_goal% tables **3 → 0**;
  re-upgrade to head → **0 → 3**. EXIT 0 both ways.
- Goals suite: `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=...
  MAISTRO_TEST_DATABASE_URL=... uv run pytest packages/maistro-core/tests/goals
  -q` → **70 passed, 0 failed, 0 skipped**.
- No second execution identity: `grep -rn "GoalRun\|OrchestratorRun"
  packages/*/src` → exit 1 (0 hits).
- Convergence freeze at exact CI argv
  (`.github/workflows/formal-conformance.yml:76`):
  `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db94`
  → **EXIT 0** ("no unapproved new architecture island").
- Docs-only delta re-proven: `git diff --stat 1f81c113d..HEAD` = the round-89…
  round-93 REPAIR-NOTES files only (531 insertions, zero non-docs). The code
  tree is byte-identical to the round-89 full-battery tree.
- Local-only environmental failure re-confirmed: `quality/ac-state.json` is
  untracked and gitignored (`.gitignore:81`), which is why
  `tests/test_branch_independence_repository.py::
  test_every_quality_json_state_surface_is_classified_once` fails only in this
  worktree; CI passed it (its 1 failure = the ledger test above).

## 5. Verdict

**BLOCKED** — unchanged, and re-proven by execution this round. All issue
acceptance criteria pass first-hand; the sole red X in CI
(`test: failure` → execution-lifecycles ledger test) cannot be repaired inside
this branch without violating the two-merge rule, weakening a mandated
criterion, or a GitHub mutation this lane is forbidden to perform. Unblock
path: **merge grant-only PR #1938 (head 2f5dd46969fc) to develop**, then sync
this branch — rounds 74/77/81/93 executed the simulation: the gate then exits 0
(`authorized: maistro.goals.model::GoalStatus … 20 vocabularies`) and the
shipped-ledger test file passes 29/29 with **zero branch edits**.

Docs-only round (this notes file); no code, test, or ledger changes; no
inventory delta (driver inventory ok at 16334).
