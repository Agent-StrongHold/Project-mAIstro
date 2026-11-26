# #2059 round-17 repair validation at b87815f2fc (job 5e457a3eb05e42afa8c451b86e655317)

Verified: 2026-11-25, worktree /home/dev/Git/wt/cr-2059, start head `b87815f2fca4`
(== assigned dispatch head, tree clean), base `90002c42d37d` (== origin/develop, unchanged).

## Headline change this round: the PR is now pushed and mergeable

`gh api pulls/2059` → **head == `b87815f2fca4` == local HEAD** (the integrator pushed the
round-16 merge commit `2840d211eb8` and note `b87815f2fca4`), `mergeable: true` — the
round-16 CONFLICTING/DIRTY residual is **cleared on the GitHub side**. Branch 57 ahead /
0 behind origin/develop → **develop-sync block resolved, no new conflict**.

## Exact-head hosted evidence (first time verifiable, all green)

- Check-runs at `b87815f2fca4`: **130 completed = 129 success + 1 skipped, 0 failed,
  0 in-progress** (two paginated calls).
- Workflow runs at the head: **14/14 completed success** (quality, CI, security×2,
  Vulture Ratchet, mutation, Gate C, CodeQL, DevSkim, Formal Conformance, Integration
  Scope, Registry CI, Cage Guard — incl. both `pull_request` and `push` events).

## gates-ran pending — root-caused stale, evaluator would publish success

Legacy commit status `gates-ran` = **pending** ("Required execution evidence is still
arriving", posted 20:49:57Z by publisher run 134947). Root cause: the `push`-event
`quality` run on the same head (19:41:49→21:11:44Z) was in flight at publish time; its
completion fired publisher 134948 with `event=push`, skipped by the job `if` (only
`pull_request`/`merge_group` publish). No later PR-event producer completes → status not
refreshed. **Decisive check (CI-exact, live API data):** collected 130 check-runs +
46 changed files for PR #2059 and ran `scripts/check-gates-ran.py --check-runs …
--require-complete --base-branch develop --event-name pull_request --changed-files …`
with **both** origin/develop's script (what the publisher executes) and HEAD's script:
**both exit 0 — "ok: all 74 required check(s) ran on this head"**. The pending verdict
is stale; any subsequent `pull_request`-event publisher firing publishes success.
Flipping the visible status needs a GitHub-side re-trigger (push/re-run) — lane-prohibited.

## Merge-integrity proofs (re-executed)

| Check | Evidence |
|---|---|
| Sole semantic delta | parsed-YAML leaf walk vs origin/develop: **total deltas: 1** = ADDED `jobs.quality-vulture.steps[6].if` (topic-push-only guard) |
| No silent ledger edits | `git diff origin/develop --numstat -- quality/` = only `+17 quality/ac-state-notes/fix-vulture-single-owner-1357.json` (intentional) |

## Validation battery at b87815f2fca4 (all executed this round)

| Gate (CI-exact argv) | Result |
|---|---|
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **exit 0**, 1220 reviewed identities = 1220 findings, unclassified 0, never_allowlist 0, base `90002c42d37d` / candidate `b87815f2fca4` |
| `uv run ruff check .` | "All checks passed!" |
| `uv run ruff format --check .` | "3665 files already formatted" |
| `python3 scripts/check-required-checks.py` | exit 0 |
| `python3 scripts/check-workflow-write-safety.py` | exit 0 |
| `python3 scripts/check-branch-protection.py` | exit 0 |
| `python scripts/check-adr-status-language.py` | exit 0 |
| `uv run python scripts/check-ratchet-provenance.py` | exit 0 |
| `uv run python scripts/check-shipped-surface-truth.py` | exit 0 |
| `uv run python scripts/check-backlog-consistency.py` | exit 0 |
| `uv run python scripts/check-suite-inventory.py` | exit 0 (no new suites → no inventory-note delta required) |

Focused tests (executed, **422 passed, 0 failures**): ownership/gates 232
(test_ci_vulture_ownership, test_check_gates_ran, test_check_required_checks,
test_gates_ran_merge_group_scope) + surface 60 (grype-floor, devskim-scope,
docker-advisory-floors, restore-oracle ×2, zip-floor) + develop-merge 130
(test_check_adr_status_language + _provenance, test_check_ratchet_provenance,
test_m1_542_policy_coverage).

## Residuals (all GitHub-side, lane-prohibited here)

1. **gates-ran visible status is pending** on a fully-green head — stale per evaluator
   (exit 0 both script versions); a new PR-event publisher firing (push/re-run) flips it.
2. **PR body line 6 negated close keywords** ("does not close #1357, #160 or #1605") —
   GitHub parses closers despite negation; #160/#1605 are OPEN and would auto-close on
   merge. Body reword only.
3. **PR body figure drift** (cosmetic): "337 focused tests" vs 422 measured this round;
   "55 collisions" vs live count.
