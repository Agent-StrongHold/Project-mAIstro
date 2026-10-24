# Repair notes — auto-34 CI gate round (supply-chain advisory drift)

Round: repair at lane L34, head 115d946e643daf6461e801f5a18a702a125cf30b, base 4de7e906d9dc.
Scope: the four failing checks reported from the last merge-queue evaluation at that head.
No issue-#34 acceptance surface (portability CONNECT tranche) was modified; the branch diff
proves it touches no dependency manifests (`git diff origin/develop...HEAD --stat` lists no
uv.lock / pyproject / package.json), so all four failures are registry-advisory drift that
develop fails identically. Fixes are lockfile-only, evidence-driven from the fetched job logs
(read-only API fetches; no GitHub mutations).

## Root causes (from the actual CI job logs, fetched read-only)

1. `Supply chain (pip-audit)` (security.yml `supply-chain`, job 120850043546) — gate log names
   the unbanked advisories: `fastmcp==4.0.11 GHSA-7xgj-8392-5q4r -> upgrade to 4.1.2`,
   `fastmcp==4.0.11 GHSA-vqqp-x5qm-5qp4 -> upgrade to 4.1.2`,
   `setuptools==84.0.0 GHSA-xmj3-9gf7-h52w -> upgrade to 84.1.0`.
   The `security` workflow failure (job 120850043596) is the same supply-chain leaf
   (identical excerpt per the dispatch findings).
2. `Container scan + SBOM + cosign` (job 120850043548) — Trivy on `maistro-engine-research`:
   `Total: 3 (HIGH: 3, CRITICAL: 0)` — pypdf 6.21.1, CVE-2026-115572 / CVE-2026-115580 /
   CVE-2026-115585, all `fixed` in 6.21.2. `Dockerfile.research` installs the committed
   `uv.lock` (`uv export --locked`), so the pin is the fix vector.
3. `test` (ci.yml, job 120850043699) — every pytest step PASSED (the two
   `RuntimeError: Event loop is closed` lines are a `PytestUnhandledThreadExceptionWarning`
   from an aiosqlite worker thread in a passing maistro-server suite, log lines 1795/1810;
   the suite ends `643 passed, 9 skipped`). The failing step is
   `npm audit --audit-level=high` in `packages/maistro-canvas/frontend`:
   `6 vulnerabilities (3 moderate, 3 high)` (body-parser, undici, zod) → exit 1.
4. Same docker-build log also prints the hive-conductor frontend `npm ci` vulnerability
   summary (`1 high severity vulnerability` — zod <4.6.6). `npm ci` does not gate on it, but
   it is the same advisory class and was fixed in the same stroke.

## Fix (3 files, lockfile-only)

- `uv.lock` — `uv lock --upgrade-package fastmcp --upgrade-package setuptools --upgrade-package pypdf`:
  fastmcp 4.0.11→4.1.3 (≥4.1.2), fastmcp-slim 4.0.11→4.1.3, openapi-pydantic 0.5.1→0.6.0
  (fastmcp 4.1 requirement), pypdf 6.21.1→6.21.2, setuptools 84.0.0→84.2.1, beartype
  dual-pin for ≥3.15. No `scripts/pip_audit_gate.py` ALLOWED amendment needed — the gate
  instructs "Fix by upgrading the dependency", and that is what this does.
- `packages/maistro-canvas/frontend/package-lock.json` — `npm audit fix`
  (@vitest/mocker+spy 5.0.5, body-parser 2.4.0, undici 7.30.1, zod bumps; package.json unchanged).
- `packages/hive-conductor/frontend/package-lock.json` — `npm audit fix` (zod 4.4.3→4.6.7; package.json unchanged).

## Local proof (all commands executed in this worktree)

- `uv sync --locked --all-extras` — clean.
- CI-exact pip-audit pipeline: `uv pip freeze --exclude-editable > /tmp/deps.txt`;
  `uv run pip-audit --strict --format=json -r /tmp/deps.txt` (attempt 1, report complete);
  `uv run python scripts/pip_audit_gate.py /tmp/pip-audit.json` →
  `pip-audit OK (1 known, all triaged in ALLOWED)` + `direct-dependency usage OK` — exit 0.
- `npm audit --audit-level=high` in canvas frontend → exit 0, `found 0 vulnerabilities`
  (was exit 1, 3 high). `npm run test:ci` → 79/79 passed; `npm run lint` → 0 errors;
  `npm run build` → success.
- `npm audit --audit-level=high` in hive-conductor frontend → exit 0, 0 vulnerabilities;
  `npm run lint` → 0 errors; `npm run build` → success.
- Vulture ledger, CI's exact arguments:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  → exit 0, 1298 findings / 1302 reviewed, no unbanked identities, no ledger amendment.
- `uv run ruff check .` + `uv run ruff format --check .` — pass.
- `uv run pytest packages/maistro-core/tests/cli/test_portability.py -q` — 23 passed
  (branch's tranche tests unchanged); fastmcp-dependent suites after the bump:
  `packages/maistro-core/tests/tools` 499 passed, maistro-server import-surface/main/sigterm 28 passed.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` —
  inventory matches, exit 0 (no test added in this round, so no inventory-note delta).
- Gates touching issue-#34 ledgers re-confirmed: check-reachability.py,
  check-convergence-matrix.py, check-reachability-dispositions.py,
  check-backlog-consistency.py — all exit 0 (149 unreachable modules, dispositions unchanged).

## Residuals

- The research-image docker build + Trivy scan was not re-executed locally (heavy image
  build); the causal chain is closed by evidence: the only HIGH findings were pypdf 6.21.1
  fixed in 6.21.2, `Dockerfile.research` installs `uv.lock` via `uv export --locked`, and the
  lock now pins 6.21.2 with no 6.21.1 reference remaining. Remote CI confirms on next run.
- `beartype` gained a Python-3.15-only second pin (0.23.1) alongside 0.22.9 — resolver
  artifact of the fastmcp bump; supported interpreters (3.12/3.13) keep 0.22.9.

## Round 2 (this head) — reconcile-gate split-resolution, fixed by develop sync

Next CI evaluation (security run 40102023193 at 8df101efe, job 120895964684) moved the
failure inside the same `Container scan + SBOM + cosign` job: every Trivy scan passed
(the develop merge had carried pypdf 6.21.2, closing the previous residual) and the new
failing step was `Reconcile installed packages to uv.lock`:

```
image maistro-engine:pr-2302 does NOT reconcile to the lock:
  version mismatch     : beartype==0.22.9 (image) != beartype==0.23.1
```

Root cause (evidence-driven from the fetched job log, read-only API): the merged uv.lock
splits beartype across environment markers — `0.22.9 ; python_full_version < '3.15'` and
`0.23.1 ; python_full_version >= '3.15'`, both marker-conditional in the export. The
gate's `parse_expected` keyed pins by name alone, so only the last line's version
survived and a correct Python 3.13 image shipping the `<'3.15'` pin was reported as a
version skew — a false positive contradicting the script's own contract ("conditional
pins gate nothing"). The repair is **not a ledger or gate edit**: develop's f956a8142
(`1182-image-lock-split-resolution.md`) already carries the upstream fix — the checker
now keeps every version of a split resolution and accepts whichever branch the image's
interpreter resolves, while still failing any version neither branch pins.

Fix: `git merge origin/develop` (7be3b70ef) — clean merge; the only overlapping files
(two frontend package-locks) were byte-identical on both sides. Nothing else changed;
no issue-#34 acceptance surface touched.

Local proof (this worktree):
- develop's `tests/test_check_image_lock_reconciliation.py` — 32 passed on the merged
  tree; 4 split-resolution tests fail against the pre-merge checker (old script extracted
  to /tmp), including the exact CI case (`shipped 0.22.9`), so the tests name the
  regression.
- Real maistro-engine image built from the merged tree
  (`docker build -f Dockerfile -t maistro-engine:pr-2302 .`), then the gate run with
  CI's exact invocation: `OK: maistro-engine:pr-2302 ships exactly the locked set
  (128 distributions, incl. 3 workspace member(s); 14 marker-conditional pin(s)
  evaluated leniently)`, exit 0.
- Marker-evaluated export simulation (py3.13/linux) reproduces the CI failure
  byte-for-byte on the old checker and accepts on the new one.
- `uv lock --check` consistent; `uv sync --locked --extra dev` clean.
- Battery: `ruff check` / `ruff format --check` pass; vulture gate with CI's exact
  arguments passes (1298 findings / 1302 reviewed, base f956a8142, no unbanked
  identities, no ledger amendment needed); portability + merged-run-concurrency +
  resource-policy suites 94 passed / 19 skipped; suite inventory matches for
  packages/maistro-core/tests, packages/maistro-server/tests and root tests/;
  check-reachability.py / check-convergence-matrix.py / check-reachability-dispositions.py /
  check-backlog-consistency.py all exit 0 (149 unreachable modules, dispositions
  unchanged).
- hive-conductor's export contains no beartype pin at all, so the second reconcile
  invocation never had this failure mode; hive/research/rsi images were not rebuilt
  locally (heavy) — remote CI verifies those invocations on the merged tree.
