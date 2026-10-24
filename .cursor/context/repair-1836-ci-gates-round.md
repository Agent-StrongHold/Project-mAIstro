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

## 6. Round 2026-10-24T05:00Z (head d71dc03) — `Container scan + SBOM + cosign`

What failed at d71dc03 (job 120767046648, fetched read-only): step 14, trivy
scan of maistro-engine-research — **only** OS `libbrotli1 1.1.0-2+b7`
CVE-2026-111497 (fixed 1.1.0-2+deb13u1); all four builds, the other three
scans, and the earlier `npm audit` digest text were not the failure.

Root cause: **apt mirror-propagation race, not a tree defect.** CI rebuilt
`production-apt` fresh (`--no-cache-filter`, line 6882 of the job log) at
03:35Z and the mirror still served b7; the deb13u1 upload reached the public
CDN shortly after (three independent fresh builds on this host resolve it:
`local-repair` ~04:00Z, `pr-2262` ~04:30Z, `repair-verify` ~04:50Z on
2026-10-24). The d71dc03 commit message's mirror theory was directionally
right but its timing claim ("a fresh build heals it") was not yet true when
CI ran — it is true now.

No code, lock, Dockerfile, workflow or `.trivyignore.yaml` change: the finding
is fixed upstream, so suppressing it would violate the ignore file's own
policy ("removed rather than silently renewed") and weaken the gate. The
gate's `--no-cache-filter production-apt` (#795) is exactly the mechanism that
self-heals this on the next run.

Fresh proof, CI-exact commands (trivy 0.73.0, DB 2026-10-24, ignorefile
`.trivyignore.yaml`, `--severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed`):

- `docker buildx build --no-cache-filter production-apt -f Dockerfile.research
  --load .` → image carries `libbrotli1 1.1.0-2+deb13u1` (dpkg-query) and
  `pypdf 6.21.2` (importlib.metadata); trivy → **rc 0, zero HIGH/CRITICAL**.
- Same fresh-stage rebuild + scan for the other three gated images: maistro-engine,
  maistro-rsi-runner, hive-conductor (with VITE build args per security.yml) →
  all **rc 0**, all layers "0: Clean".
- Canvas `npm audit --audit-level=high` (ci.yml:698) → rc 0, 0 vulnerabilities.
- `uv sync --locked --all-extras`; `pip-audit --strict` +
  `scripts/pip_audit_gate.py` → rc 0 (only triaged ecdsa PYSEC-2026-1325).
- `uv run ruff check .` / `ruff format --check .` clean;
  `scripts/check-adr-status-language.py` ok; `git diff --check` clean; tree
  clean before this note.

Residual: GH-runner CDN edges may lag this host by minutes-to-hours; if the
next `Container scan + SBOM + cosign` run still shows CVE-2026-111497, re-run
the job (it is a mirror race again — same evidence rules apply) rather than
suppressing. The issue's owner-acceptance act on SPEC-101826-1836 remains open
by design and is unaffected by this gate repair.

## 7. Round 2026-10-24T08:20Z (head 822547d3, unchanged) — the predicted
residual materialized, now on maistro-rsi-runner

What failed at 822547d3 (job 120790272270, run 40066333928, fetched read-only
via `gh api .../actions/jobs/120790272270/logs`): only the trivy scan of
`maistro-rsi-runner:pr-2264` — `libbrotli1 1.1.0-2+b7` CVE-2026-111497 (HIGH,
fixed `1.1.0-2+deb13u1`). The `npm audit fix` lines in the log digest are the
hive frontend build stage's `npm ci` advisory summary (step `#27`, exits 0;
the real audit gate, ci.yml:698 on canvas, passed — the `CI` workflow at this
head is green). Every other workflow at this head is green: `quality`,
`Vulture Ratchet`, Gate C, Formal Conformance, Registry CI, Integration Scope,
SAST (Bandit/Semgrep/Gitleaks), pip-audit, DevSkim, Cage Guard.

Forensics — the finding is not reproducible from the tree, and the job's own
log contradicts its scan:

- The rsi-runner build (05:38:15, `--no-cache-filter runtime-apt` present at
  security.yml:289-295) rebuilt the apt stage fresh and **installed the fixed
  version**: log lines `Get:54 ... libbrotli1 amd64 1.1.0-2+deb13u1`,
  `Unpacking libbrotli1 (1.1.0-2+deb13u1)`, `Setting up libbrotli1
  (1.1.0-2+deb13u1)` (05:38:25–05:38:32) — then exported and `--load`-ed
  (05:39:40–05:40:30) before the 05:44:22 scan. Six minutes earlier the
  research image's `production-apt` stage pulled the identical `deb13u1` from
  the same `trixie-security` suite, and its scan is clean in the same job.
- Fresh CI-exact rebuild on this host at the identical tree:
  `docker buildx build -f Dockerfile.rsi-runner -t
  maistro-rsi-runner:local-repair-1836 --no-cache-filter runtime-apt --load .`
  → rc 0; fetched/unpacked/set up `1.1.0-2+deb13u1` (build log Get:54);
  `/var/lib/dpkg/status` in the image: `Version: 1.1.0-2+deb13u1`; trivy
  0.73.0 with CI's exact arguments (`--severity HIGH,CRITICAL --exit-code 1
  --ignore-unfixed --ignorefile .trivyignore.yaml`) → **rc 0, zero
  HIGH/CRITICAL**.

Disposition: no in-tree defect — no Dockerfile, lock, workflow, or ignore-file
change (suppressing the CVE would violate `.trivyignore.yaml`'s own policy;
hand-pinning the package would go stale against the #795 design). The
mechanism is the same one section 6 documented, now settled: the mirror serves
`deb13u1` consistently (two independent hosts, three builds), and the red scan
contradicts the job's own successful upgrade, so the next `Container scan +
SBOM + cosign` run — which rebuilds `runtime-apt` fresh and scans the freshly
loaded tag — is expected green. Evidence rules from section 6 apply to the
next red, if any.

No-ledger-change proof: `uv run python scripts/check-vulture-baseline.py
packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → rc 0, 1302
reviewed identities == 1302 findings, unclassified 0, never_allowlist 0 — the
CI-repair clause's amend/remove legs are both vacuous at this head; the branch
carries no quality/ ledger delta beyond `quality/ac-state-notes/auto-1836.json`
(+17/-0, numstat vs base `4de7e906d9dc`).

Driver battery re-run live at this head: `uv run ruff check .` rc 0; `uv run
ruff format --check .` rc 0; `scripts/check-adr-status-language.py` rc 0; `git
diff --check` rc 0; `uv run python scripts/check-suite-inventory.py` rc 0 (21
suites match — invoke via `uv run`, a bare `python3` lacks pydantic for the
bare_python suites, same as CI's `uv pip install --system` step provides).
Develop base motion re-resolved by fetch: origin/develop `4de7e906d9dc` ==
merge-base == assigned base; branch is develop + exactly the six in-scope
files; no sync conflict. No test added/moved/removed — no inventory delta
(stays as recorded). The issue's owner-acceptance act on SPEC-101826-1836
remains open by design and is the only non-environmental residual.
