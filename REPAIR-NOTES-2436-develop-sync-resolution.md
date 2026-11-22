# #2436 develop-sync conflict resolution (this round)

Branch `dependabot/npm_and_yarn/packages/hive-conductor/frontend/typescript-7.0.2`.
Starting head `7db39aaebdd279594217c85f4cff6697c8da5ea4` (prior round's repair
commit), develop base at dispatch `dc8c3e756d1a5da3ec282a888b2819c72fb5b763`
(= origin/develop tip, still current at end of round).

## Preserved state found

A merge of `546e72c040…` (develop tip minus one commit) into the branch was in
progress and preserved with one unresolved conflict (UU):
`packages/hive-conductor/frontend/package.json`. All other merge entries were
auto-staged; three files (develop's `REPAIR-NOTES-2437-develop-sync-resolution.md`
and the #2432/#2437 inventory notes) had merged cleanly from the develop side.
The prior attempt died on a provider rate limit mid-merge; nothing was wiped.

## Resolution

- `packages/hive-conductor/frontend/package.json`: union of both sides — the
  branch's file verbatim, which already carries develop's converged stack
  (`@vitejs/plugin-react ^6.3.0`, `eslint-plugin-react-refresh ^0.5.8`,
  `vite ^8.3.8`) plus this PR's reconciled content: `typescript ~6.0.3` and the
  scoped `openapi-typescript → typescript: "$typescript"` override. Why not
  7.0.2: native typescript-go 7.x ships no classic JS compiler API, so
  `typescript-eslint` (peer `<6.1.0`) cannot parse and `openapi-typescript`
  (peer `^5.x`) cannot run — every `npm ci` consumer redded on the original
  bump (verified analysis in 831cd8ad40). ~6.0.3 is the maximal viable bump.
- Second merge completed the sync: develop tip `dc8c3e756d1a` = `546e72c040` +
  the Python-only #2424 commit (`apply_recovered_attempt_disposition`), no
  overlap with this branch's surfaces.
- Net three-dot diff vs `origin/develop`: exactly
  `packages/hive-conductor/frontend/package.json` (+7/−1) and
  `package-lock.json` (typescript spec 5.9.3 → ~6.0.3, lock resolves 6.0.3).
  All branch CI/workflow/test narratives converged byte-identically with
  develop's (#2432/#2437 rounds); `scripts/js_dependency_gate.py` identical.
- `git diff --numstat origin/develop -- quality/` empty: no ledger drift, no
  amendment (the delta touches no Python source).
- Tree-wide conflict-marker sweep over tracked non-md files: clean.

Committed as `116ab4828f` (merge of 546e72c040) and `b42e385a27` (merge of
develop tip dc8c3e75); worktree clean.

## Executed validation (all green, CI-exact invocations)

- `npm ci && npm run lint && npm run build` in `packages/hive-conductor/frontend`
  (ci.yml:684): install OK (207 pkgs, no ERESOLVE — lock integrity holds with
  the override), lint exit 0 (0 errors, 48/96 warnings), `tsc -p
  tsconfig{,.node}.json --noEmit` + vite build exit 0.
- `node --test tests/ci/integration-scope.test.cjs` (ci.yml:1732): 14/14 pass.
- JS supply chain (security.yml "JS supply chain" job, reproduced end to end):
  `npm audit --package-lock-only --json` reports for all three tracked
  surfaces, `scripts/js_guarddog_scan.py --output-dir` real GuardDog reports,
  then `scripts/js_dependency_gate.py` with all six reports: **exit 0**
  (inventory, lock, license, provenance, typosquat, install-script,
  vulnerability, malicious-package all pass; frontend's 7 moderate audit
  findings adjudicated by the exceptions ledger, same set develop reports).
- `docker build --target frontend -f packages/hive-conductor/Dockerfile`: rc=0
  — the image's `RUN npm ci` (node:26-alpine) installs the bumped lock; this
  is the exact stage docker-build/Gate C/containers/e2e execute.
- Full runtime image `docker build -f packages/hive-conductor/Dockerfile -t
  maistro-engine:local .` (compose's image name): rc=0, includes the frontend
  dist from the bumped-lock stage.
- `scripts/verify-compose-durability.sh` (ci.yml hive-conductor-compose-
  durability, exact invocation): **34 passed, 0 failed** — create, write,
  recreate (down/up + image replacement), read, backup, restore; post-restore
  login/session/settings/credential checks hold against the rebuilt image.
- `hive-conductor-e2e-ui` exact command (`docker compose -f
  docker-compose.test.yml --profile test up --build --abort-on-container-exit
  --exit-code-from e2e-tests e2e-tests` with the harness key env): **229/229
  Playwright tests pass**, exit 0.
- `hive-conductor-e2e` exact command (`--exit-code-from api-tests api-tests`):
  14 passed, 14 skipped (gateway-less harness skips, same profile as CI),
  exit 0.
- Focused pytest: `tests/test_buildx_build_retry.py tests/test_mutation_targets.py
  tests/test_js_dependency_gate.py tests/test_check_gates_ran.py
  tests/test_check_integration_scope.py tests/test_pr_scope_policy_parity.py
  tests/test_ci_merge_group_scope.py tests/test_ci_merge_group_outputs.py
  tests/test_pinned_digest_references.py -q`: **241 passed**.
- `uv run ruff check .` — all checks passed; `uv run ruff format --check .` —
  3616 files already formatted.
- Vulture ledger gate, CI's exact args (`scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`): base
  dc8c3e756d1a, candidate b42e385a27e0, 1221 reviewed identities = 1221
  findings, exit 0.
- `scripts/check-workflow-inventory.py` (33 workflows),
  `scripts/check-required-checks.py` (79 PR checks),
  `scripts/check-suite-inventory.py` (21 suites match recorded inventory — no
  test-count delta; no new inventory note required),
  `scripts/check-test-duplicates.py`, `scripts/check-backlog-consistency.py`:
  all exit 0.

## Residual (for integrator)

- Container scan + SBOM + cosign: the job's build prerequisite is proven green
  above; the scanner/sign tool legs themselves run only on CI runners and were
  not reproduced locally.
- Gate C (canonical clean install): its core path — clean state → compose
  bring-up → migrations → healthy → auth checks — is exercised repeatedly by
  the durability scenario above against the same image; the workflow's own
  script was not re-run locally (pulls litellm/langfuse fleet images).
- `gates-ran` aggregation will judge the pushed head; no push performed
  (campaign prohibition: no GitHub mutations from worker).
