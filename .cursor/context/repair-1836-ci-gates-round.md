# Repair #1836 round — `test` + `Container scan + SBOM + cosign` gates (branch auto-1836, head 8d31f1806)

Starting head `8d31f18067cbbb77e56fbe198a907e3075ec0dd0` (assigned, clean), base
`4de7e906d9dc9f74ed47f240abc94221db102a66`. All claims below were re-derived in
this tree; CI logs were fetched read-only (`gh api .../actions/jobs/<id>/logs`,
jobs 120750758457 `test`, 120750758565 `Container scan + SBOM + cosign`).

## 0. What actually failed at 8d31f1806 (from the job logs, not the digest)

- `test` job: every pytest step, both frontend builds, generated-types diff,
  canvas test/lint/build, hive backend, cross-suite and inventory steps all
  PASSED. The only failing step is `npm audit --audit-level=high` in
  `packages/maistro-canvas/frontend` (ci.yml:698): 3 HIGH (body-parser
  GHSA-27r3-jxmh-p828, undici GHSA-4qv8-2p9j-2685/f72v-6w45-q472/xjj6-f33q-929c,
  zod GHSA-mrhx-c7xc-m3w5) + 3 moderate. The two `##[error] raise
  RuntimeError('Event loop is closed')` annotations are
  `PytestUnhandledThreadExceptionWarning` text from aiosqlite's
  `_connection_worker_thread` in a PASSING server test
  (tests/api/test_user_model_api.py) — the same non-fatal annotation shape the
  #859 round documented; the step containing them exited 0.
- `Container scan + SBOM + cosign` job: builds and the hive-conductor +
  maistro-engine trivy scans PASSED. The failing step is the **trivy scan of
  maistro-engine-research**: OS `libbrotli1 1.1.0-2+b7` CVE-2026-111497 (fixed
  1.1.0-2+deb13u1) + python-pkg `pypdf 6.21.1` CVE-2026-115572/115580/115585
  (fixed 6.21.2). The `npm audit fix` lines in the log digest are `npm ci`
  output from the hive frontend build stage (advisory summary only; that step
  exits 0 and is not a gate).

## 1. Root causes

- Canvas: stale `package-lock.json` — advisories landed after the last lock
  sync. Branch-agnostic (same shape as #859's vite round).
- Research image: (a) `pypdf 6.21.1` is transitive (via `browser-use`) in the
  committed `uv.lock`; (b) the deb13u1 brotli security upload postdates the CI
  build's mirror state — `production-apt` re-consults the mirror only when the
  stage is rebuilt, which is exactly what security.yml's
  `--no-cache-filter production-apt` (#795) does. No Dockerfile change needed.

## 2. Repairs (regenerated, not hand-pinned; no gate weakened, no advisory suppressed)

1. `packages/maistro-canvas/frontend`: `npm audit fix --package-lock-only` →
   `found 0 vulnerabilities` (package.json untouched).
2. `uv.lock`: `uv lock --upgrade-package pypdf` → 6.21.2 (hash-verified
   artifacts; the only uv.lock delta of this round).

## 3. Local evidence (CI's exact commands / CI-exact equivalents)

- `npm audit --audit-level=high` (canvas) → rc 0, `found 0 vulnerabilities`
  (was rc 1, 6 vulnerabilities).
- Canvas gate sequence: `npm ci` (0 vulns) → `npm run test:ci` (5 files / 79
  passed) → `npm run lint` (0 errors, 13 pre-existing warnings) → `npm run
  build` (✓ built).
- `docker buildx build --no-cache-filter production-apt -f Dockerfile.research
  --load .` (CI's flag; a plain cached `docker build` replayed the pre-advisory
  apt layer and still showed b7 — do not trust a cached rebuild) → artifact has
  `libbrotli1 1.1.0-2+deb13u1` (dpkg-query) and `pypdf 6.21.2`
  (importlib.metadata); `import maistro_server.main` ok.
- `trivy image --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed
  --ignorefile .trivyignore.yaml maistro-engine-research:local-repair` (trivy
  0.73.0 — CI's pinned version, fresh DB) → **rc 0, zero HIGH/CRITICAL**.
- `uv sync --locked --all-extras`; `uv pip freeze` → `pip-audit --strict` →
  `scripts/pip_audit_gate.py` → `pip-audit OK` (only triaged ecdsa
  PYSEC-2026-1325), exit 0.
- `uv run pytest tests/test_distribution_contract.py` 6 passed (pypdf floor
  6.19.0 satisfied by 6.21.2; `_locked_export` runs the image's exact export);
  `tests/test_dependency_namespaces.py tests/test_check_image_lock_
  reconciliation.py tests/test_engine_canvas_packaging.py` → 98 passed, 3 skip.
- `ruff check .` / `ruff format --check .` clean; `scripts/bump_version.py
  --check` (42 sites, 0.9.0) and `scripts/check-release-consistency.py` ok;
  `scripts/check-suite-inventory.py` → ok, 21 suites match (run with a py3.12
  venv holding hive `backend/requirements.txt` — the two `bare_python` suites
  need pydantic in the *invoking* interpreter, as CI gets from
  `uv pip install --system`); `scripts/check-test-duplicates.py` ok.

## 4. No test-count delta

No pytest test was added, moved, or removed; no vitest file changed. Suite
inventory baseline needs no delta note for this round (node IDs unchanged;
inventory gate re-run green above).

## 5. Residual risks (for the next round — do not redo, just carry)

- `packages/hive-conductor/frontend` still audits zod GHSA-mrhx-c7xc-m3w5
  (high). NOT gate-blocking: ci.yml runs the audit gate only for canvas, and no
  runtime image ships node_modules (frontend stage produces static assets
  only; trivy scans of the built images are green). A one-line
  `npm audit fix --package-lock-only` there is the eventual fix if a gate ever
  covers it.
- Advisories keep landing against locks on unchanged trees; every "green"
  verify round that does not re-run `npm audit`/trivy is one advisory away
  from this shape.
