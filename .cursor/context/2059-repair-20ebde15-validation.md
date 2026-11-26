# CR-2059 repair round 9 — validation at exact head `20ebde159c1f`

Round 9 (2026-11-25). Branch `fix/vulture-single-owner-1357`, head `20ebde159c1f986cde45103f6dcf43027504bd4b`, base `c9636e99f1d77efe24fdc6f4c07a3bfc3bea3ae2`. Tree was clean at start; this note is the only change in this round. No production file was touched: all issue acceptance is re-proven by execution, not inherited from prior rounds' claims.

## Carried-over block: develop sync

Resolved before this round (merge commit `9bfc7428ce`); re-verified:

- `git merge-base --is-ancestor c9636e99f1 HEAD` → exit 0.
- Local `origin/develop` = `c9636e99f1` (no new develop commits to absorb).
- `git status --short` clean at start of round.

## Sole semantic workflow change (re-proven, not assumed)

- `git diff --stat origin/develop...HEAD -- .github/workflows/` → `quality.yml` only, +9/−2.
- Parsed-YAML recursive walk over **all** workflow files (develop vs HEAD, PyYAML): **exactly 1 delta** — `quality.yml.jobs.quality-vulture.steps[6].if` added (now `quality.yml:1601-1605`): `github.event_name == 'push' && github.ref != 'refs/heads/develop' && github.ref != 'refs/heads/integration' && github.ref != 'refs/heads/main'`. The remaining text hunk (1584-1590) is comment-only.
- `vulture-ratchet.yml` 0-line delta; still owns `pull_request` + `merge_group` + `push:[develop,integration,main]` (`vulture-ratchet.yml:9-22`). Shared events keep exactly one scan owner; Quality's copy fires only on its unique topic pushes.

## Preserved contract — same command (executed)

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → **exit 0**, base `c9636e99f1d7` → candidate `20ebde159c1f`, **1220 reviewed identities → 1220 findings, unclassified 0, never_allowlist 0**. (Issue-body figure "1,328" is stale; executed truth is 1220.)

## Focused tests (executed)

10 touched suites in one pytest run → **292 passed** (26.25s). `tests/test_ci_vulture_ownership.py` collects **exactly 80**; negative controls present and passing (`test_owner_mutations_fail_closed`, `test_duplicate_or_queue_overlap_is_not_a_valid_fallback`).

## Gates with CI-exact arguments (all exit 0)

- `check-required-checks.py` → 79 PR checks match docs.
- `check-uv-setup.py` → 74 uv-install steps.
- `check-workflow-write-safety.py` → 33 workflows, no unseen writes.
- `check-branch-protection.py` → 21 required on develop, 35 on main.
- `check-suite-inventory.py` → 21 suites match recorded inventory (no test added this round; no inventory delta needed).
- `check-backlog-consistency.py` → 167 items resolve.
- `ruff check .` and `ruff format --check .` → exit 0.

## Still outside lane authority (unchanged from prior rounds, re-checked live)

1. **Hosted rollup at exact head UNVERIFIED**: `gh run list` at `20ebde159c1f` shows 12 workflow legs created 2026-11-25T17:00:52Z all `queued`/`pending`, 0 completed, 0 failed. Merge must await drain; nothing red so far.
2. **PR/issue body defects (GitHub-side only)**: body retains "This PR does not close #1357, #160 or #1605" — GitHub ignores negation for closer keywords and `#160`/`#1605` are OPEN, so merging would auto-close them; figures stale vs executed (1,328 vs 1220; 337 vs 292; "keep draft" vs `isDraft:false`). Body edit is a GitHub mutation — prohibited for this lane; must be reworded GitHub-side before merge.

## Verdict inputs

All in-tree acceptance criteria re-proven green at the exact head. Residuals are exclusively GitHub-side (body reword) or timing (hosted queue drain). No in-tree repair is warranted.
