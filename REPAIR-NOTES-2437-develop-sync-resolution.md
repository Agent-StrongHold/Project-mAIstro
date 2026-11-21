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

---

# #2437 develop-sync round 2 (develop tip `1621f7fefba`)

## State found

Develop advanced past `fc1bea9936` to `1621f7fefba` (#2434, #2345, #2445
landed), so the PR conflicted against develop tip again. A merge of
`1621f7fefba…` into the branch was in progress, preserved with two unresolved
conflicts (UU): `.github/workflows/integration-scope.yml` and
`tests/ci/integration-scope.test.cjs` — both comment-narrative hunks of the
evidence paragraph both sides have been extending since #2437's repair. All
other merge entries (incl. develop's `quality/` rows, mutation/workflow
changes, #2445 e2e dep bump, #2345/#2434/#2445 inventory notes) auto-merged.

## Resolution

- Code values: develop's shipped budget (245-minute timeout / 480 x 30s
  attempts) kept — already outside the conflict hunks; both new test
  assertions pin it.
- `.github/workflows/integration-scope.yml` narrative: develop's latest text
  (#2433 budget death detail, "PR #2435 then expired it again") with the
  branch's PR #2437 candidate-side measurement (run 44748434713, job
  136329705554, ~124 min queue, success 16:40:50–16:59:24Z) appended before
  the shared conclusion. No evidence lost from either side.
- `tests/ci/integration-scope.test.cjs`: develop's enumeration raised to
  "four times" and extended with the #2437 parenthetical (run 44748434713).
- `git diff --numstat origin/develop -- quality/` empty: no ledger drift; no
  amendment needed (the bump touches no Python source).
- PR intent intact: `eslint-plugin-react-refresh ^0.5.8` in
  `packages/hive-conductor/frontend/package.json:30`; lock resolves 0.5.8;
  the merged frontend lockfile differs from develop's by exactly that one
  package (261 -> 261 entries, no transitive movement).
- Tree-wide conflict-marker sweep over tracked non-md files: clean.

Merged and committed as `31c532dcda346b760ccbd42e4dd259672258efd3`; worktree
clean.

## Executed validation (all green)

- `node --test tests/ci/integration-scope.test.cjs` (CI's exact command,
  ci.yml:1732): 14/14 pass, incl. the starvation-timeline tests and the
  245/480 budget assertions.
- `uv sync --locked --extra dev`: venv matches the merged `uv.lock`.
- `uv run ruff check .` — All checks passed; `uv run ruff format --check .` —
  3613 files already formatted.
- Focused pytest `tests/test_check_gates_ran.py tests/test_js_dependency_gate.py
  tests/test_mutation_targets.py tests/test_buildx_build_retry.py -q`:
  169 passed.
- Vulture ledger gate, CI's exact args
  (`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`): base 1621f7fefba4, candidate 31c532dcda34,
  1221 reviewed identities = 1221 findings, exit 0.
- `scripts/check-suite-inventory.py`: 21 suites match the recorded inventory
  (no test-count delta this round — the .cjs changes are comments only; no new
  inventory note required). `scripts/check-workflow-inventory.py`: clean (33
  workflows). `scripts/check-required-checks.py`: ok, 79 PR checks.
- npm audit `--package-lock-only --json` on the merged frontend lockfile:
  7 moderate findings (`@typescript-eslint/*` chains + minimatch) — the
  identical set develop reports; fed through
  `js_dependency_gate.check_audit_report` with each tree's locked versions:
  **0 findings on the branch tree and 0 on develop's** (the
  `VULNERABILITY_EXCEPTIONS` ledger covers the root advisory; via-chains
  produce none of their own). Pure policy legs (`check_lock_drift`,
  `check_provenance`, `check_licenses`, `check_typosquats`) run directly on
  all three surfaces (frontend, canvas frontend, e2e): OK. GuardDog reports
  are CI-step artifacts and were not reproduced locally; the scan list is
  direct deps and no direct dep changed version in this PR.

## Result

The develop-sync blocker for #2437 is resolved at head `31c532dcda` with
`origin/develop` tip `1621f7fefba` as second parent; the three-dot diff vs
develop is exactly the bump (frontend package.json/package-lock.json), the
#2437 evidence-window repair (workflow + test narrative, 14/13 line deltas),
the prior rounds' repair note + inventory note, and the
`tests/test_buildx_build_retry.py` tweak. Not pushed (campaign prohibition:
no GitHub mutations from worker).
