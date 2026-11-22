# Repair notes — issue #35 lane (auto-35), CI-gate repair round

Starting head `59a4df4bb8f9d20aa0958ad1225f86d99906bb81` (clean, = declared head;
develop base `4de7e906d9dc9f74ed47f240abc94221db102a66`, still origin/develop's tip at
repair time — no sync conflict). The previous repair round made **no commit**; that
block is resolved here: this round commits.

## What failed in the merge-queue evaluation and why

Four check-runs failed at `59a4df4b`: `test`, `security` (ci.yml), `Supply chain
(pip-audit)` and `Container scan + SBOM + cosign` (security.yml). Every quality ratchet
specific to the branch's code (vulture, reachability, execution-lifecycles,
convergence-matrix, coverage, e2e, docker-build, exact-debt-ledger) was already green.
The branch itself adds no dependency, manifest, lockfile or Dockerfile change — all four
failures are dependency-advisory drift that hits develop identically:

1. **pip-audit (both `security` and `Supply chain` run one gate script).** Reproduced
   locally: `uv pip freeze --exclude-editable` + `pip-audit --strict --format=json` +
   `scripts/pip_audit_gate.py` → exit 1, "advisories outside the triaged allowlist":
   `fastmcp==4.0.11` GHSA-7xgj-8392-5q4r (CVSS v3 ≈ 7.0 HIGH) and GHSA-vqqp-x5qm-5qp4
   (≈ 5.8 MED, both fixed in 4.1.2), `setuptools==84.0.0` GHSA-xmj3-9gf7-h52w (fixed in
   84.1.0). Advisories published against develop's own locked pins after its last green
   run; `git diff origin/develop..HEAD -- uv.lock packages/*/pyproject.toml` is empty.

2. **`npm audit --audit-level=high` in `packages/maistro-canvas/frontend`** (the `test`
   job's terminal error, exit 1): undici ×3 (2 high), zod (high), ip-address (moderate)
   — all with non-breaking fixes. Reproduced locally; the branch never touched that
   tree.

3. **Container scan + SBOM + cosign**: the four images install from `uv.lock`
   (`uv export --locked`), so the freshly published fastmcp HIGH shipped inside the
   `maistro-engine` image venv (`maistro-server[image]` closure carries fastmcp) and
   trivy's `HIGH,CRITICAL --ignore-unfixed --exit-code 1` failed the job. Separately,
   `packages/hive-conductor/Dockerfile` hard-pins `setuptools==84.0.0` ("the lock's own
   setuptools version" per its own comment) — stale once the lock moved.

4. **`Event loop is closed` log lines in the `test` job**: non-fatal log noise. The job
   continued past them (they precede root-suite PASSED lines and the job's terminal
   error is npm audit). Every suite the job runs was reproduced green locally at this
   head (see below); the noise did not reproduce and no tree change is warranted.

## The repair (lockfile + the two pins that must follow the lock)

- `uv.lock`: `uv lock --upgrade-package fastmcp --upgrade-package setuptools` →
  fastmcp/fastmcp-slim 4.1.3, setuptools 84.2.1, transitive openapi-pydantic 0.6.0.
  No manifest change (`fastmcp>=3.2.0,<5` already allows 4.1.x).
- `packages/maistro-canvas/frontend/package-lock.json`: `npm audit fix` (lockfile-only;
  `package.json` untouched) → `npm audit --audit-level=high` now "found 0 vulnerabilities".
- `packages/hive-conductor/Dockerfile`: the setuptools exact pin follows the lock,
  `84.0.0` → `84.2.1`, per the comment's own contract.
- `.github/workflows/security.yml`: the image-lock-reconciliation member must match the
  Dockerfile pin, `--member setuptools==84.0.0` → `84.2.1`.

## Local proof, CI's exact arguments

- pip-audit gate on the new freeze: `pip-audit --strict --format=json` (exit 1 is
  findings, as in CI) then `python scripts/pip_audit_gate.py` → **exit 0**
  ("pip-audit OK (1 known, all triaged in ALLOWED); direct-dependency usage OK").
- Canvas frontend: `npm audit --audit-level=high` → **exit 0**; `npm ci`, `npm run
  test:ci` (79/79), `npm run lint` (0 errors), `npm run build` all pass.
- Images rebuilt from the repaired tree and scanned with CI's exact trivy invocation
  (`--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 --ignorefile
  .trivyignore.yaml`): `hive-conductor` **exit 0** (ships setuptools 84.2.1),
  `maistro-engine` **exit 0** (ships fastmcp 4.1.3).
  `scripts/check-image-lock-reconciliation.py` on the rebuilt hive-conductor image with
  the updated member list → **OK, 72 distributions**.
- License inventory (`scripts/check-license-inventory.py --only …`) on the three
  surfaces the repair touches — canvas npm tree (post-audit-fix), and both rebuilt
  images → **exit 0** each.
- Suites (post-upgrade venv): hive-conductor backend **3974 passed, 26 skipped**;
  root `tests/` **5638 passed, 143 skipped**; maistro-server **644 passed**;
  maistro-core security/extensions/capabilities **3488 passed**; turing **350**;
  design **660**; ext-harness/sdk **420**. The #35 contract tests specifically:
  `test_dag_run_projection_authority.py` + `test_dag_run_projection_lifecycle.py` +
  `test_dag_run_history_durability.py` → **61 passed**.
- `uv run ruff check .` / `ruff format --check .` → green; suite inventory gate
  (`--suite packages/hive-conductor/backend/tests`) → ok at 4000 collected (2937 base +
  unfolded deltas incl. this lane's two +15 notes).

## Residual risks

- `maistro-engine-research` and `maistro-rsi-runner` images were not rebuilt/scanned
  locally; their fastmcp is lock-sourced (`uv export`/`uv sync --locked` both resolve
  4.1.3 now), so the fix mechanism is identical. OS-layer findings are a function of the
  Debian security mirror at build time and are branch-independent.
- The cosign/sign and Grype steps were not executed locally (no cosign/grype binaries);
  Grype `--only-fixed --fail-on high` keys off the same now-fixed versions.
- The `Event loop is closed` CI log noise is unreproduced (non-fatal; all suites green
  locally).

No `quality/*.json` ledger was touched (not a vulture-ledger repair round; no Python
source changed). No tests added or removed — inventory notes unchanged and still
truthful (+15/+15, matching the 4000-collected gate).
