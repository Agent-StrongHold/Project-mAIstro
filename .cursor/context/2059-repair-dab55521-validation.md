# CR-2059 repair round 11 — validation at exact head `dab555214ea5`

Round 11 (2026-11-25). Branch `fix/vulture-single-owner-1357`, head `dab555214ea55ab80863d2ec446a08345db8539e`, base `c9636e99f1d77efe24fdc6f4c07a3bfc3bea3ae2`. Tree was clean at start (no uncommitted salvage); this note is the only change in this round — no source change was warranted. Every claim below is re-executed at this head, not inherited.

## Carried-over block: develop sync (stale — re-proven resolved)

The dispatch brief again listed "develop sync conflict preserved in worktree". It is stale: `git fetch origin` then `git rev-parse origin/develop` → `c9636e99f1…`, byte-identical to the assigned base, so there is nothing to merge. `git rev-list --left-right --count HEAD...origin/develop` → `51 0` (ahead only). Resolution merge `9bfc7428ce` remains in ancestry (`git merge-base --is-ancestor c9636e99f1 HEAD` → exit 0). Tree clean before and after validation. Live `gh pr view 2059` → `mergeable: MERGEABLE`.

## Sole semantic workflow change (re-proven, not assumed)

- Parsed-YAML recursive canonical walk over `quality.yml` (develop `c9636e99f1` vs HEAD, PyYAML): **exactly 1 delta** — the added leaf `jobs.quality-vulture.steps[6].if`: `push && ref ∉ {develop, integration, main}` (`quality.yml:1602-1606`). Zero removed/changed leaves beyond it.
- `vulture-ratchet.yml` has a **0-line diff** vs develop; it owns `pull_request` + `merge_group` + `push:[develop,integration,main]` (`vulture-ratchet.yml:9-15`) with a **byte-identical** scan command to `quality.yml` (verified programmatically: both extract to the same `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` block). Shared events keep exactly one scan owner; Quality's copy fires only on its unique topic pushes.

## Preserved contract — same command (executed)

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → **exit 0**, base `c9636e99f1d7` → candidate `dab555214ea5`, **1220 reviewed identities → 1220 findings, unclassified 0, never_allowlist 0**. No exact-debt-ledger failure occurred, so no ledger amendment was needed or made: `git diff --numstat c9636e99f1..HEAD -- quality/` shows only the additive `ac-state-notes/fix-vulture-single-owner-1357.json` (+17/−0); `vulture-baseline.json` diff vs develop is empty.

## Focused tests (executed)

- 13 PR-touched suites in one pytest run (ownership, gates-ran ×2, required-checks, ratchet-provenance ×2, shipped-surface-truth, and the 6 develop-sync suites) → **405 passed** (42.16s), 0 failed.
- `tests/test_ci_vulture_ownership.py` alone collects **exactly 80**, including the fail-closed negative controls.

## Gates with CI-exact arguments (all exit 0)

- `check-required-checks.py` → 79 PR checks match `docs/ci/REQUIRED-CHECKS.md`; develop queue SQUASH.
- `check-uv-setup.py` → 74 uv-install steps through the pinned wrapper.
- `check-workflow-write-safety.py` → 33 workflows, no unseen writes.
- `check-branch-protection.py` → 21 required on develop, 35 on main.
- `check-suite-inventory.py` → 21 suites match recorded inventory (no test added this round; no inventory delta needed).
- `check-backlog-consistency.py` → 167 backlog items resolve.
- `check-ratchet-provenance.py` → 0 lifecycle violations vs base; 55 quality-JSON consumers have explicit provenance.
- `check-shipped-surface-truth.py` → matrix complete.
- `ruff check .` → "All checks passed!"; `ruff format --check .` → 3664 files already formatted.
- `check-gates-ran.py` itself needs live check-run artifacts (`check-runs.json`, `changed-files.json`) and cannot run standalone; its unit suites `test_check_gates_ran.py` + `test_gates_ran_merge_group_scope.py` pass in the battery above.

## Hosted rollup at exact head — drain advanced, still 0 failures

Live `gh pr view 2059` (query 2026-11-25T17:5xZ): **118 success / 10 in_progress / 0 failed**, `isDraft: false`, `MERGEABLE`. Completed-success legs include every vulture-ownership-critical check at the exact head: `exact-debt-ledger`, `Quality / Vulture` (both), `workflow-lint`. Still draining (routine heavyweight, 0 failed anywhere): `integration-scope`, `coverage (no services)` ×2, `coverage (PostgreSQL)` ×2, `test`, `Container scan + SBOM + cosign`, `docker-build` (+ unnamed annotation entries). Full split-profile green must await the drain before merge; nothing red exists at this head.

## Still outside lane authority (GitHub-side, unchanged)

1. **PR body premature-closure hazard**: body retains "This PR does not close #1357, #160 or #1605" — literal `close #160` / `close #1605` closer keywords (GitHub ignores negation); #160/#1605 are OPEN, so merge to the default branch would auto-close them. Body edit is a GitHub mutation — prohibited for this lane; must be reworded GitHub-side before merge. (#1357 is CLOSED/inert.)
2. **Stale PR body figures vs executed truth**: "1,328 reviewed identities" → 1220; "337 focused tests" → 405 this round; "root suite inventory matches 5,066 cases" → 21 suites recorded; "Keep draft pending exact-head hosted checks" → PR is already `isDraft: false`. Same GitHub-side constraint.

## Round verdict

No code repair was warranted: the head is unchanged from round 10, and every locally-provable acceptance criterion re-executed green at it. Residuals are exclusively the GitHub-side body reword and the external hosted drain.
