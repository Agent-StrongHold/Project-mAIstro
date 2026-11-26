# REPORT-1641 — fix-forward merge of stale PR #1641

Branch: `m1/1641-closeout-fixforward-20261017`
Merge commit: **5a5db13f8** (`Merge PR #1641 (1e4363d6): named cross-product-parity job + strict M1 closeout mode`)
Base: `ab8b3737f` (develop tip, "#1627 beam selection")
PR head merged: `1e4363d611a0f06529a16b31a66232df5a59cd5e` (PR #1641 head; itself a merge of PR work + develop@9556a157b)

## 1. Commands run and outcomes

| # | Command | Outcome |
|---|---------|---------|
| 1 | `git fetch origin pull/1641/head` | FETCH_HEAD = 1e4363d6 (matches expected PR head) |
| 2 | `git merge --no-ff --no-commit FETCH_HEAD` | Auto-merged 8/9 files; exactly one conflict: CHANGELOG.md (as parent predicted) |
| 3 | `python3 scripts/check-branch-protection.py` | **PASS** — "ruleset agrees with the workflows (19 on develop, 31 on main)" |
| 4 | `python3 scripts/check-required-checks.py` | **PASS** — "34 PR checks match docs/ci/REQUIRED-CHECKS.md; develop queue is SQUASH … merge_group" |
| 5 | `python3 scripts/check-workflow-inventory.py` | **FAIL → fixed → PASS.** Initial: `cross-product-parity-strict.yml: no entry in quality/workflow-inventory.json` (this gate postdates the PR's merge base). Added MANUAL_DIAGNOSTIC disposition → "clean (29 workflow(s) dispositioned)" |
| 6 | `uv sync --locked --extra dev` | OK |
| 7 | `uv run python scripts/check-suite-inventory.py` | **PASS** — 17 suites match inventory; `tests/: 5213` includes the PR's `tests/: +3` note delta; 0 duplicate evidence |
| 8 | `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest tests/cross_product_parity -q` | **PASS** — 12/12 (development mode) |
| 9 | Same + `MAISTRO_PARITY_STRICT=1` | **4 failed, 8 passed** — designed behavior: exactly the 4 scaffold-only scenarios (1/2/3/6) fail closed on their REAL_* blockers; matches the PR/workflow's documented "expected to fail today until #1036 lands" |
| 10 | `uv run python scripts/check-ac-state.py --run-tests --ratchet` (exact Quality-gate step, push variant) | **FAIL (inherited)** — `design_coverage: 39.641 falls below the floor of 44.2377`; see §4 |
| 11 | `uv run python scripts/check-ac-state.py --run-tests --ratchet --bank` | Banked `quality/ac-state-notes/m1-1641-closeout-fixforward-20261017.json` (measured state: all 10 debt counters at ceilings, design_coverage 39.641) |
| 12 | `uv run ruff check <2 changed .py files>` + `ruff format --check` | **PASS** — "All checks passed! / 2 files already formatted" |
| 13 | `/tmp/actionlint -no-color -oneline -shellcheck /tmp/shellcheck-bin` (actionlint 1.7.7 + shellcheck 0.10.0 — CI's exact pinned versions, all workflows) | **PASS** (exit 0, no findings) |
| 14 | `python3 scripts/check-uv-setup.py`, `python3 scripts/check-workflow-write-safety.py` | **PASS** — "29 workflow step(s) install uv 0.12.5 through the wrapper"; "29 workflow(s) make no writes the gate set cannot see" |

Diagnostics (temp worktree `/tmp/measure-1641-develop`, removed afterwards):

| Command | Outcome |
|---------|---------|
| `RATCHET_BASE_REV=ac7370141 uv run python scripts/check-ac-state.py --run-tests --ratchet` on **develop tip** (ab8b3737) | **FAIL with the identical failure**: `design_coverage: 39.641 falls below the floor of 44.2377` — develop itself cannot pass this step |
| Same, with a simulated `design_coverage@39.641` grant at base (#1853 pattern) + candidate commit | **PASS** — "OK: 10 debt counters sit exactly on their ceilings and 1 progress counter sits exactly on its floor" |

## 2. Conflict resolution rationale (CHANGELOG.md)

- The repo uses squash merges (no merge commits in CHANGELOG history), and every recent PR's entry lands at the **top of the first `### Added` section under `[Unreleased]`** (verified: #961/#2008 Oct 6, #1736/#96 Oct 3, #1955/#1087 Oct 5 all prepend there).
- Resolution: develop's side kept 100% intact (verified post-resolution: `git diff origin/develop -- CHANGELOG.md` shows **only** the PR entry as the delta); the PR's #459 entry inserted **verbatim** (byte-identical to FETCH_HEAD's block, verified by diff) at the top of the first `### Added` section. Neither side's entries dropped.
- Mid-resolution self-inflicted duplication of the `#103 campaigns` heading over the `#101 BacklogItem history` body was caught by grep and corrected; final file verified: one `#103` entry, `#101` entry intact, zero conflict markers.

## 3. Semantic-completeness check (merge result vs PR head, per file)

| File | vs PR head | Notes |
|------|-----------|-------|
| `.github/branch-protection.json` | +1 line | develop-side only ("docs" topic label added after the PR's base). PR's two `cross-product-parity` context lines present; counts verified 19/31 by gate #3. **No equivalent develop content — PR's addition is new.** |
| `.github/workflows/ci.yml` | develop-side changes only | PR's `cross-product-parity` job block **byte-identical** (verified by block diff). Pre-merge grep confirmed develop had **no** parity job/naming anywhere — no silently-dropped hunks. |
| `.github/workflows/cross-product-parity-strict.yml` | identical | — |
| `docs/ci/BRANCH-PROTECTION.md` | identical | consistent with merged JSON (19/31, gate #3) |
| `docs/ci/REQUIRED-CHECKS.md` | develop-side table rows only | PR's `cross-product-parity` row present; machine-verified by gate #4 (generator output == merged table, 34 checks) |
| `docs/testing/inventory-notes/claude-ws-459-...b993.md` | identical | delta verified live by gate #7 |
| `tests/cross_product_parity/harness.py` | identical | — |
| `tests/cross_product_parity/test_cross_product_parity.py` | +2 lines | develop-side only (`DEFAULT_TEST_ACTOR_PRINCIPAL_ID` import + `actor_principal_id=` kwarg on `create_run`, landed on develop after the PR's base). PR's tests/scenario changes fully present. |
| `CHANGELOG.md` | entry relocated | PR entry verbatim at top of first `### Added`; develop entries preserved |

**Verdict: no file had equivalent develop content that silently absorbed PR hunks. Develop took none of this PR's content independently; every PR hunk survives.**

## 4. Ratchet outcome (Quality gate step `acceptance-state ratchet + mandate`)

Reproduced the remote failure exactly, then isolated it:

- The step fails with `design_coverage: 39.641 falls below the floor of 44.2377`.
- The floor comes from `quality/ac-state-notes/auto-1572.json` (44.2377), which landed on develop **2026-10-13 via #1938** — banked from a stacked-branch tree. No commit since then touched docs/adr or docs/specs, so develop measured below that floor from the moment it landed. **Measured directly: develop tip (ab8b3737) fails its own ratchet step with the identical numbers.** Every develop push and every PR candidate since Oct 13 inherits this failure.
- PR #1641 is not the cause: its diff touches no specs, ADRs, or `@pytest.mark.ac` markers (verified: 0 hunks matching), so the merged tree's design_coverage equals develop tip's.
- **Banking cannot fix it** (by design): notes fold by `max`, and the candidate's own note is excluded from the fold it is judged against. I banked the honest measured note anyway (the gate's own printed remedy; also the companion artifact a grant references, per the #1853 precedent).
- **Proven remediation (not shipped here, out of authority/scope):** a floor grant `design_coverage@39.641` with owner/issue/reason in `quality/ratchet-authorizations.json` must land on **develop first** (exactly the #1853 "chore(quality): authorize design_coverage fall …" pattern, PR #1853 → #1841). Simulation in an isolated worktree confirmed the exact step then passes with all counters at their bounds. Per AGENTS.md's two-merge rule ("a grant never authorizes the change that introduces it") and the no-grant-edits-in-implementation-PRs constraint, this branch must not carry its own grant.

Nothing was weakened: no floor/ceiling edits, no test deletions, no ratchet-script changes.

## 5. Files changed by this lane (beyond the merge itself)

- `quality/workflow-inventory.json` — MANUAL_DIAGNOSTIC disposition for `cross-product-parity-strict.yml` (required by the workflow-inventory gate, which landed on develop after the PR's merge base; the gate is part of the same "Quality gate (Pillars 1–4, 7, 8)" job).
- `quality/ac-state-notes/m1-1641-closeout-fixforward-20261017.json` — banked measured ac-state note (see §4).

## 6. Remaining risks / findings

1. **BLOCKER (pre-existing, not PR-caused):** the `acceptance-state ratchet + mandate` step cannot pass on any develop-based candidate until a `design_coverage@39.641` floor grant lands on develop (owner decision; #1853 precedent). Publishing this branch without that grant will reproduce the one red check on the PR head. Nothing in this lane can or should fix that unilaterally.
2. The `cross-product-parity-strict.yml` workflow is designed to be red today (fails on CONDUCTOR_INSPECTION/REAL_* blockers until #1036 and real scenarios land). It is dispatch-only and outside the required-check contract — not a publication blocker.
3. The new `cross-product-parity` job is unscoped (no `needs: workflow-lint` / path filter) while develop's newer specialized jobs are classifier-scoped. It always reports on every PR and merge-group candidate, which is safe for a required context (no Expected-forever); the generator and merge-queue gates accept it (gates #3/#4 pass). Cosmetic alignment with the scoping pattern is optional future work.
4. `quality/ac-state.json` (measurement output, git-ignored) was regenerated in the worktree — no repo impact.
5. Suite inventory: the PR's `tests/: +3` note is live-verified (5213 collected); no other suite's collection changed.
