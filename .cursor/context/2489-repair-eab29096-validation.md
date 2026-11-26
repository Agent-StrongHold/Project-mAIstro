# CR-2489 repair round — validation at exact head `b251a04ec1`

Round 2026-11-26, job `eab2909604d74c1b91703e63367e7fac`. Branch
`dependabot/npm_and_yarn/packages/hive-conductor/tests/e2e/esbuild-0.28.2`,
head `b251a04ec1d63eccb63775bd2971dc593505432b`, base
`7ba29c1cd0e45d0fa3ccc9cef807173e52b3c75d` (develop). Tree was clean at start;
this note is the only change in this round. No production file was touched:
every changed-hunk claim below is re-proven by execution, not inherited from
prior attempts (both prior rounds made no commit and produced no evidence).

## PR substance (esbuild 0.28.1 → 0.28.2) — proven, not assumed

- `git diff base...HEAD --name-only` → exactly 2 files:
  `packages/hive-conductor/tests/e2e/package.json` (+`"esbuild": "^0.28.2"`),
  `packages/hive-conductor/tests/e2e/package-lock.json`.
- Lockfile diff = 29 hunks, all confined to `node_modules/esbuild` + the 26
  `node_modules/@esbuild/*` platform binaries (0.28.1 → 0.28.2, resolved URLs
  and integrity hashes updated). No other package touched.
- `npm ci` from the PR lockfile in an isolated copy → **exit 0** (10 packages);
  `esbuild --version` → **0.28.2**.
- Real bundle via the specs' own API path (`build({bundle, platform:"browser",
  format:"iife", jsx:"automatic", minify})` — the `deck-sanitization.spec.ts:99`
  harness pattern) on a TSX entry importing `react-dom/client` → **bundle ok**
  with esbuild 0.28.2.

## CI evidence at this exact head (check-runs API, read-only)

Integration scope classifies this PR's paths (`ci_merge_group_scope.py` +
`check-integration-scope.py`, executed locally) to required =
**docker-build, hive-conductor-e2e, hive-conductor-e2e-ui, wheel-imports**.
Newest-attempt-by-id conclusions for all four: **success** (ids 139985749627,
139985749729, 139985749671, 139985749696; completed 14:46:05–15:02:53Z). Also
green at head: JS supply chain, lint-and-type-check, exact-debt-ledger, full
Quality suite, docker-build, postgres pg17/pg18, `test`.

## Sole red gate: `integration-scope` — proven stale, not a code defect

- Check-run 139984921689 failed 14:42:56Z, 11 s after start. Its GitHub
  annotation reads verbatim: `docker-build is required by integration scope but
  concluded cancelled`.
- Timeline: a zero-duration cancelled batch of check-runs (ids 139984942450–
  139984944315, created 14:42:42–44Z, cancelled 14:42:44Z) was the *newest
  attempt by id* at the aggregator's first sample; the successful re-run batch
  (ids 1399857…) did not exist until 14:44:38Z. The aggregator's fail-closed
  rule ("newest cancelled attempt supersedes success", pinned by
  `tests/ci/integration-scope.test.cjs` "latest unsuccessful completed check
  fails even when an older check succeeded") fired on the stale sample.
- Deterministic replay of the *shipped* script (`vm` sandbox, real ids):
  T0 snapshot → fails with exactly the observed annotation; current snapshot
  (cancelled + newer success batch) → passes: "all integration-scope
  specialized evidence succeeded". The gate is green on merits; only a
  GitHub-side re-run of the integration-scope workflow (or a new push) clears
  the stale red. That re-run is a GitHub mutation this lane is prohibited from
  performing — **handoff action for the maintainer**.
- `node --test tests/ci/integration-scope.test.cjs` locally → **14/14 pass**;
  no test gap exists (fail-fast-on-cancelled is already pinned), so no test
  was added and no inventory delta is owed.

## Deterministic battery (driver logs + re-executed)

- Driver `check-0/1/2.log`: `uv sync --locked --extra dev`, `uv run ruff
  check .` (All checks passed), `uv run ruff format --check .` (3675 files
  already formatted) — all exit 0; change set is npm-only.
- `python3 scripts/check-required-checks.py` → 79 PR checks match docs, exit 0.
- `python3 scripts/check-uv-setup.py` → 74 uv-install steps through the
  wrapper, exit 0.

## Residual risk

Branch protection will still show `integration-scope` red until the workflow is
re-run at `b251a04ec1`; all evidence it waits for already exists and succeeds.
`gates-ran` inherits that redness. The other in-flight check at capture time
(Coverage gate, started 15:11:41Z) is unrelated to this change set and still
running at capture; no verdict is taken from it.
