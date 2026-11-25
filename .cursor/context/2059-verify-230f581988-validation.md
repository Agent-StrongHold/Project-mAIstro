# #2059 independent verification — round 6 (2026-11-25, head 230f58198817)

Lane CR2059 verify, job `a1b765a6bbb04bb987c15d966a985118`. Head
`230f58198817` (= PR #2059 head as dispatched), tree clean at dispatch,
base `bd96877ed8ccd0` fully contained (merge-base = `bd96877ed8ccd0`).
Head is docs-only vs round-5's `e219077258f0` (one new context note,
61+/0-). All evidence below re-executed fresh at `230f58198817`; the
round-5 "worktree_changed" rejection cause is addressed by capturing all
evidence before this note was written.

## Executed evidence

1. **Sole semantic workflow change**: `git diff bd96877ed8..HEAD --
   .github/workflows/` = quality.yml only; vulture-ratchet.yml 0-line.
   Parsed-YAML walk (PyYAML) over every changed workflow file → exactly
   **1** differing node: `jobs.quality-vulture.steps[6].if` ADDED
   (`push` && ref ∉ {develop, integration, main}).
2. **Ownership preserves event coverage**: vulture-ratchet.yml (unchanged)
   triggers on `pull_request` (no filter), `merge_group
   [checks_requested]`, `push [develop, integration, main]` — it is the
   single owner of every shared event; quality.yml's vulture step keeps
   exactly Quality's unique topic-branch pushes. No event is
   double-scanned or unscanned.
3. **No forbidden #1357 hunks**: `git diff bd96877ed8..HEAD -- packages/
   migrations/ quality/vulture-baseline.json` → 0 lines. `quality/`
   numstat vs base additive-only 17+/0- (ac-state note).
4. **CI-exact vulture scan** `uv run python scripts/check-vulture-baseline.py
   packages/*/src --min-confidence 60 --exclude '*/third_party/*'` →
   **exit 0**, 1221 reviewed identities → 1221 findings, vulture 2.16,
   base `bd96877ed8cc`, candidate `230f58198817`.
5. **Focused tests**: ownership/gates suites (test_ci_vulture_ownership,
   test_check_gates_ran, test_check_required_checks,
   test_gates_ran_merge_group_scope) → **232 passed**; collect-only on
   test_ci_vulture_ownership → **80** (exact). Negative re-run (`-k "reject
   or missing or duplicate or narrow or override or candidate or
   broaden"`) → **10 passed**: 25 fail-closed workflow mutations × 2
   owners, duplicate/queue-overlap fallback rejected.
6. **Merge-queue repair tests**: grype floors, docker-CLI advisory floors,
   temporalio zip floor, devskim scope, restore-oracle characterization +
   readiness → **60 passed**.
7. **Local gates**: `check-required-checks.py` exit 0 (79 checks match
   docs/ci/REQUIRED-CHECKS.md); `check-suite-inventory.py` exit 0 (21
   suites); `ruff check .` exit 0; `ruff format --check .` exit 0 (3659
   files). Driver logs agree (uv sync, ruff check, ruff format all pass).
8. **No premature closure**: closure-keyword grep over
   `bd96877ed8..HEAD` bodies → exit 1; PR body explicitly does not close
   #1357/#160/#1605.
9. **Live read-only rollup** (`gh pr view 2059 --json
   statusCheckRollup,headRefOid,isDraft` at `230f58198817`, head matches
   local): 25 legs **QUEUED**, 1 COMPLETED (SKIPPED — Container scan,
   path-filtered), **0 failed**, `isDraft: False`, state OPEN. Hosted
   required-check green on this exact head remains **UNVERIFIED** until
   the queue drains; merge must await the hosted rollup.

## Known GitHub-side staleness (lane-prohibited body edit; unchanged from round 5)

- Body "1,328 reviewed identities" vs measured **1221** (scan exit 0 at
  a23fec659dd4, e219077258f0, 230f58198817).
- Body "337 focused … tests" vs measured **232 + 60 repair**; "80 new
  ownership cases" IS exact.
- Body "Keep draft pending exact-head hosted checks" vs live
  `isDraft: False`.
