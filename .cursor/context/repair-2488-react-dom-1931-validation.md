# Issue #2488 (PR) — repair round CR2488: react-dom 19.2.0 → 19.3.1 in /packages/hive-conductor/tests/e2e

Phase: repair, job `74e8a5a9a29145cfb7ecc07578570f8f`. Starting head `9d0c1a375d41b475d87668489cc4581bf01f0a44`
(branch `dependabot/npm_and_yarn/packages/hive-conductor/tests/e2e/react-dom-19.3.1`),
base `7ba29c1cd0e45d0fa3ccc9cef807173e52b3c75d` (= head's parent; **no develop sync conflict**).
Prior attempt (job `556fad1a…`) validated but committed nothing; this round re-derived every claim
from raw evidence and left this record as the round's commit. No code changes were needed — the
change is a two-file dependency-manifest bump and every executable check passed.

## The one RED on head, reproduced from captured CI evidence (99 check-runs @ 2026-11-26T15:38:27Z)

- `integration-scope` (run 45841746517, job 139984930649) failed 14s after starting (14:42:56→14:43:10Z).
- Root cause: wave-1 jobs (run 45841744232) were cancelled 14:42:42–44Z (concurrency supersession).
  The gate (`.github/workflows/integration-scope.yml`) uses latest-check-run-id-per-name and fails
  closed on any non-success; at 14:43:10Z the latest run of all four required legs was `cancelled`.
  Reconstructed with the gate's own algorithm over the captured runs: all four → `cancelled` at that
  moment. This is the documented starvation/supersession transient, not a scope defect.
- All four required legs re-ran (wave 2) and concluded **success** on this exact SHA:
  docker-build 139985725401 (15:03:03Z), hive-conductor-e2e 139985725183 (14:55:18Z),
  hive-conductor-e2e-ui 139985725396 (14:49:44Z), wheel-imports 139985725315 (14:45:28Z).
  Re-applying the gate algorithm over the full capture: **the gate would pass on re-run**.
- A new wave was already in flight at capture: `gates-ran` status `pending`
  ("Required execution evidence is still arriving", 15:33:46Z → run 45850287281). The gate re-run
  itself is CI-side; workers may not trigger GitHub mutations.

## Repair round evidence (all executed locally unless noted)

| Check (CI-exact where possible) | Result |
|---|---|
| `git diff --no-renames --name-only 7ba29c1cd0...HEAD` | exactly 2 files: `tests/e2e/package.json`, `tests/e2e/package-lock.json` |
| manifest: `react-dom` | `^19.2.0` → `^19.3.1`; lock: 19.3.1, integrity `sha512-Y0bARz…`, scheduler 0.28.0, peer `react ^19.3.1` |
| `npm ci` (node 22.22.1 / npm 9.2.0) in tests/e2e | **exit 0** — lockfile ↔ manifest sync + integrity proven |
| `npm ls --all` | exit 0; react-dom 19.3.1 + react 19.3.1 + scheduler 0.28.0, @playwright/test 1.65.1 unchanged |
| `renderToStaticMarkup` on 19.3.1 | `<div id="probe">render-ok</div>` — package functional |
| specs' esbuild harness pattern (bundle `react-dom/client` entry) | 1.85 MB bundle w/ `createRoot` impl + 19.3.1 marker; executes into real react-dom runtime (throws its genuine "Target container is not a DOM element." guard outside a browser — expected) |
| `uv run python scripts/ci_merge_group_scope.py --json <2 changed paths>` | `{"docker_build": true, "durable_events": false, "hive_e2e": true, "object_storage": false, "postgres": false, "strike_ladder": false, "wheel_imports": true}` |
| `uv run python scripts/check-integration-scope.py --event-name pull_request --scope-json <above> --required-json` | `["docker-build","hive-conductor-e2e","hive-conductor-e2e-ui","wheel-imports"]` — matches captured legs |
| `node --test tests/ci/integration-scope.test.cjs` | **14/14 pass** (gate logic conformance) |
| `uv run pytest tests/test_playwright_harness_version_parity.py -q` | **3 passed** (covers @playwright/test parity; react-dom has no parity contract) |
| stale-version grep `19\.2\.0` in tests/e2e (ts/py/md/json, minus node_modules) | none (exit 1) |
| `tests/Dockerfile.playwright` inline `react@19.2.0 react-dom@19.2.0` pins | **unchanged vs base** (empty diff) — separate harness-image contract, pre-existing; hive-conductor-e2e-ui built it and concluded success on this SHA |
| JS supply chain (npm audit + GuardDog + policy gate), job 139984933091 | **success** 14:45:15Z on this SHA (captured evidence); Supply chain (pip-audit) + security also success |
| driver checks (this job's check-0/1/2.log) | `uv sync --locked --extra dev` ok; `ruff check` "All checks passed!"; `ruff format --check` "3675 files already formatted" |

## Residual (honest unknowns)

1. `integration-scope` check-run itself is still RED on GitHub until a re-run lands — proven it
   would pass; re-run is outside worker powers (no GitHub mutations).
2. Coverage gate (139994447995) in-flight at capture (started 15:10:05Z; its wave's `test` leg
   concluded success 15:33:29Z) — final conclusion not observable from the snapshot.
3. Final `gates-ran` status pending at capture.

No tests added or removed → suite inventory unchanged; no inventory note required.
