# CR-2059 repair round 10 — validation at exact head `fc20181ecfde`

Round 10 (2026-11-25). Branch `fix/vulture-single-owner-1357`, head `fc20181ecfde0afec6d2299690510b9babc2550a`, base `c9636e99f1d77efe24fdc6f4c07a3bfc3bea3ae2`. Tree was clean at start; this note is the only change in this round. Every claim below is re-executed at this head, not inherited.

## Carried-over block: develop sync (stale — resolved, re-proven)

The dispatch brief listed "develop sync conflict preserved in worktree" as an open block. It is stale: the resolution merge `9bfc7428ce` predates round 9. Re-verified at this head:

- `git merge-base --is-ancestor c9636e99f1 HEAD` → exit 0 (develop base IS an ancestor).
- `git status --porcelain` → empty (clean tree) before and after validation.
- Live `gh pr view 2059` → `mergeable: MERGEABLE`.

## Sole semantic workflow change (re-proven, not assumed)

- Parsed-YAML recursive canonical walk over **all 33** workflow files (develop `c9636e99f1` vs HEAD, PyYAML): **exactly 1 delta** — the added leaf `quality.yml.jobs.quality-vulture.steps[6].if` (`quality.yml:1602-1606`): `push && ref ∉ {develop, integration, main}`. Zero removed leaves, zero other changed leaves, no added/removed workflow files.
- Textual workflows delta +9/−2; the second hunk (1584–1590) is comment-only.
- `vulture-ratchet.yml` **byte-identical** to develop (`diff` exit 0); owns `pull_request` + `merge_group` + `push:[develop,integration,main]` (`vulture-ratchet.yml:9-14`) with the byte-identical scan command (`vulture-ratchet.yml:82-86`). Shared events keep exactly one scan owner; Quality's copy fires only on its unique topic pushes.

## Preserved contract — same command (executed)

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → **exit 0**, base `c9636e99f1d7` → candidate `fc20181ecfde`, **1220 reviewed identities → 1220 findings, unclassified 0, never_allowlist 0**. No exact-debt-ledger failure occurred, so no ledger amendment was needed or made: `git diff --numstat c9636e99f1 HEAD -- quality/` shows only the additive `ac-state-notes/fix-vulture-single-owner-1357.json` (+17/−0); `vulture-baseline.json` untouched vs develop.

## Focused tests (executed)

- 10 PR-touched suites in one pytest run → **292 passed** (24.75s).
- `tests/test_ci_vulture_ownership.py` collects **exactly 80**, including the fail-closed negative controls.
- Provenance/shipped-surface focused suites (`test_ratchet_provenance.py`, `test_shipped_surface_truth.py`) → **112 passed** (17.13s). Round total: **404 passed, 0 failed**. (Issue-body figure "337" is stale; executed truth is 292+112 at this head.)

## Gates with CI-exact arguments (all exit 0)

- `check-required-checks.py` → 79 PR checks match `docs/ci/REQUIRED-CHECKS.md`.
- `check-uv-setup.py` → 74 uv-install steps through the pinned wrapper.
- `check-workflow-write-safety.py` → 33 workflows, no unseen writes.
- `check-branch-protection.py` → 21 required on develop, 35 on main.
- `check-suite-inventory.py` → 21 suites match recorded inventory (no test added this round; no inventory delta needed).
- `check-backlog-consistency.py` → exit 0.
- `check-ratchet-provenance.py` → all per-identity ratchets balanced vs base `c9636e99f1` (vulture 1220=1220, promotion-surface 85=85, reachability 82=82, contract-markers 358=358, …).
- `check-shipped-surface-truth.py` → matrix complete.
- `ruff check .` → "All checks passed!"; `ruff format --check .` → 3664 files already formatted.

## Hosted rollup at exact head — key upgrade this round

Live `gh api` check-runs at `fc20181ecfde` (query ~17:35Z, mid-drain): **75 success / 10 in_progress / 1 skipped / 0 failed** (was 20 queued / 0 completed at round-9 capture). Completed success includes every vulture-ownership-critical check:

- `exact-debt-ledger` (the dedicated owner) → **completed success** at the exact head.
- `Quality / Vulture` → **completed success** on the PR event (its vulture step correctly skipped by the new `if`; job green).
- `workflow-lint` (actionlint + shellcheck) → **completed success**.
- `branch-protection`-contract-adjacent legs, `pr-base`, `postgres (pg18)`, `coverage (MinIO)`, `DevSkim`, `Mutation gate`, all three `Analyze` legs, `formal-conformance`, `Gate C`, `sandbox-conformance`, `cross-product-parity`, `docker-rebuild-compare`, `block` → success.

Still in_progress at query time (routine heavyweight legs, 0 failures anywhere): `hive-conductor-e2e`, `hive-conductor-e2e-ui`, `docker-build`, `Quality / Acceptance state`, `Quality / Hypothesis`, `coverage (no services)`, `coverage (PostgreSQL)`, `Container scan + SBOM + cosign`, `integration-scope`, `test`. Full split-profile green must await drain before merge; nothing red exists at this head.

## Still outside lane authority (GitHub-side, unchanged)

1. **PR body premature-closure hazard**: body retains "This PR does not close #1357, #160 or #1605" — the literal `close #160` / `close #1605` sequences are closer keywords (GitHub ignores negation) and #160/#1605 are OPEN, so merging into the default branch would auto-close them. Body edit is a GitHub mutation — prohibited for this lane; must be reworded GitHub-side before merge.
2. **Stale PR body figures vs executed truth**: "1,328 reviewed identities" → 1220; "337 focused tests" → 292+112; "Keep draft pending exact-head hosted checks" → PR is already `isDraft: false`. Same GitHub-side constraint.

## Round verdict

All locally-provable acceptance criteria are proven by execution at the exact head. Hosted vulture-ownership proof (exact-debt-ledger + Quality/Vulture + workflow-lint at `fc20181ecfde`) is now green; only routine heavyweight legs remain draining with 0 failures. The two residual findings are GitHub-side text mutations this lane is prohibited from performing.
