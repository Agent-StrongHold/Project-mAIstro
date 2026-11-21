# #2437 develop-sync conflict resolution (this round)

Starting head: `020b3f82649256736e8e562770bae74847062f83` (branch
`dependabot/npm_and_yarn/packages/hive-conductor/frontend/eslint-plugin-react-refresh-0.5.8`).
Develop base: `fc1bea9936bb6ecd2e40625d946979839c12a520` (origin/develop tip).

## Preserved state found

A merge of `fc1bea9936…` into the branch was in progress and preserved with two
unresolved conflicts (UU): `.github/workflows/integration-scope.yml` and
`tests/ci/integration-scope.test.cjs`. All other 161 merge entries were already
auto-staged by git. No uncommitted non-merge work existed to salvage.

## Resolution

- Budget conflict (timeout-minutes / EVIDENCE_WAIT_ATTEMPTS): adopted develop's
  converged 245-minute window / 480 attempts. The branch side (190/360, from
  372f53a250) would have *regressed* trunk's wider window; 240 minutes of
  evidence strictly covers the ~124-minute starvation PR #2437 measured (run
  44748434713, job 136329705554). Evidence requirements are unchanged — the
  aggregator still fails closed on any non-success conclusion or budget
  exhaustion, so no gate is weakened.
- Comments: kept develop's #2433/#2435 evidence verbatim and appended the
  branch's #2437 measurement so neither side's documented run evidence is lost.
- `tests/ci/integration-scope.test.cjs`: took develop's assertion hunk
  (245/480); develop's two new starvation-timeline tests (#2435, #2433) were
  already outside the conflict region and are kept.
- Resolution result vs develop (6 files, +79/−9): the two resolved CI files
  (comment-only deltas), the dependabot bump
  (`packages/hive-conductor/frontend/package.json` +
  `package-lock.json` → `eslint-plugin-react-refresh ^0.5.8` / 0.5.8), this
  round's predecessor note
  `docs/testing/inventory-notes/2437-integration-scope-queue-starvation-repair.md`,
  and the branch's earlier `tests/test_buildx_build_retry.py` tweak.
- `git diff --numstat origin/develop -- quality/` is empty: no ledger drift,
  no amendment needed (the bump touches no Python source).

Merged and committed as `d6267c80a184c88b78e980663af090b58549dc68`; worktree
clean.

## Executed validation (all green)

- `node --test tests/ci/integration-scope.test.cjs`: 14/14 pass (incl. the
  #2435/#2433 starvation-timeline tests and the 245/480 budget assertions).
- `npm ci` + `npm run lint` + `npm run build` in
  `packages/hive-conductor/frontend` — CI's exact commands (ci.yml "npm ci &&
  npm run lint && npm run build"): lock integrity OK for 0.5.8; lint exit 0
  (48 warnings ≤ `--max-warnings 96`); vite build exit 0. `npm ls` confirms
  eslint-plugin-react-refresh@0.5.8 installed.
- `uv sync --locked --extra dev`; `uv run ruff check .`; `uv run ruff format
  --check .`: green.
- Vulture ledger gate with CI's exact args
  (`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`): 1221 reviewed identities = 1221 findings, 0
  unbanked/stale, exit 0.
- `scripts/check-workflow-inventory.py` (33 workflows dispositioned),
  `scripts/check-workflow-write-safety.py`,
  `scripts/check-suite-inventory.py` (21 suites match recorded inventory; no
  test-count delta — no new inventory note required),
  `scripts/check-test-duplicates.py`,
  `scripts/check-backlog-consistency.py`: all green.
- Focused pytest: `tests/test_buildx_build_retry.py` 18 passed;
  `tests/test_ci_merge_group_scope.py tests/test_ci_merge_group_outputs.py
  tests/test_check_integration_scope.py tests/test_pr_scope_policy_parity.py
  tests/test_pinned_digest_references.py
  tests/test_playwright_harness_version_parity.py` 72 passed.

## Residual (for integrator)

Full CI legs that need runners (docker-build, hive-conductor e2e(-ui),
wheel-imports, coverage floors, formal) were not executed locally; the branch's
Python delta vs develop is limited to the resolved CI files and prior-round
test tweak, all of which are covered by the focused suites above. No push, no
GitHub mutation performed.
