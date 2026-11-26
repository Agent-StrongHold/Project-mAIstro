# Repair notes — issue #1450 round 5 (container scan gate: rsi-runner OS + cargo findings)

Branch `auto-80`, head before this round: `d8b07c503a62` (develop tip
`f8a2df966` already merged — merge-base HEAD..origin/develop equals
`origin/develop`, no develop conflict remains).

## Root cause of the reported CI failure

`Container scan + SBOM + cosign` (security.yml run 43804711341, job
133092706203) failed at `Trivy scan maistro-rsi-runner (HIGH/CRITICAL only)`
— exit 1 on two distinct targets. The engine and engine-research scans in the
same job passed; the pip-audit leg of the supply-chain gate passes at this
head (re-proven below).

1. **debian 13.7 target — `linux-libc-dev` 6.12.116-1, six kernel HIGHs,
   fixed 6.12.117-1 (trixie-security).** The same run's build log disproves
   the installed version: at 04:41:38 the re-executed `runtime-apt` stage
   (`--no-cache-filter`, `Get:18 ... linux-libc-dev all 6.12.117-1`,
   `Setting up linux-libc-dev (6.12.117-1)`) installed the fixed version, yet
   the loaded tag scanned at 6.12.116-1. This is the #93/#1152 mechanism
   again: buildx computes cache keys pre-execution from the instruction
   string and parent key chain, never from a RUN's fresh bytes, so
   `--no-cache-filter runtime-apt` re-executes the apt stage but downstream
   stages still match pre-advisory cache chains (and mode=max cached
   manifests) that carry the old OS layer into the assembled image. The
   Dockerfile.rsi-runner header's re-bump doctrine applies verbatim.

2. **`workspace/.venv/lib/python3.12/site-packages/temporalio/bridge/
   Cargo.lock (cargo)` — Rust `zip` crate 8.6.0: CVE-2026-115905 (CRITICAL,
   fixed 9.0.5) + CVE-2026-115907/115908/115909 (HIGH, fixed 9.0.0).** The
   trivy DB gained these advisories between rounds; the crate ships inside
   the temporalio wheel (locked 1.34.0, 2026-09-30), vendored by its bridge
   binary, not declared anywhere in this tree. The fix exists upstream, so
   per the gate's own policy this is an upgrade, not a triage entry.

## Fix

- **uv.lock:** `uv lock --upgrade-package temporalio` → temporalio 1.34.0 →
  **1.36.1** (pyproject specifier `>=1.27.0` untouched) plus the resolver's
  matching nexus-rpc 1.4.0 → 1.5.0. temporalio 1.36.1's bridge Cargo.lock
  ships `zip` **9.5.1** (verified by unpacking the manylinux wheel from
  PyPI), past all four fix versions. Nothing in the repo imports temporalio —
  it is the RSI runner loop image's runtime dependency — so no test surface
  moves.
- **Base digest bump (#93 doctrine):** `python:3.12-slim`
  `sha256:a0f57064…` → `sha256:5e2bdb1b…` (current tag resolution, verified
  with `docker buildx imagetools inspect`) in Dockerfile.research (2 FROMs),
  Dockerfile.rsi-runner, packages/hive-conductor/tests/Dockerfile,
  deploy/sbx/template/Dockerfile.tests,
  packages/maistro-bootstrap/tests/Dockerfile.sandbox, with the
  quality/image-pins.json row re-recorded (recorded 2026-11-16, recorded_in
  #1450, note extended with this round's run/build-log evidence). No
  .trivyignore.yaml change: no entry lapsed, and no new entry is justified —
  both finding classes now have reachable fixes.

## Evidence (all executed locally at the repaired tree)

- `docker buildx build --load --no-cache-filter runtime-apt -f
  Dockerfile.rsi-runner -t maistro-rsi-runner:repair-round5 .` → RC 0; the
  apt layer logs `Setting up linux-libc-dev (6.12.117-1)` and `Setting up
  libbrotli1:amd64 (1.1.0-2+deb13u1)`; the venv contains temporalio 1.36.1
  with `zip = "9.5.1"` in its bridge Cargo.lock (`uv sync --frozen` against
  the updated committed lock).
- **Trivy 0.73.0 (CI-exact version and flags: `--severity HIGH,CRITICAL
  --exit-code 1 --ignore-unfixed --ignorefile .trivyignore.yaml --vuln-type
  os,library`) on `maistro-rsi-runner:repair-round5` → exit 0**, with the
  temporalio Cargo.lock target explicitly assessed at 0 findings and OS =
  debian 13.7 with zero HIGH/CRITICAL rows.
- **Falsification fixture:** the same scanner against
  `temporalio==1.34.0` installed into the same base reproduces the CI
  failure exactly (zip 8.6.0, CVE-2026-115905 CRITICAL + 3 HIGHs, exit 1),
  and its un-upgraded base additionally flags zlib1g 1:1.3.1-1+b1 — proving
  the clean scan comes from the fixes, not scanner/DB blindness.
- Supply-chain leg (ci.yml `security` job, CI-exact): `uv pip freeze
  --exclude-editable` → `uv run pip-audit --strict --format=json` →
  `scripts/pip_audit_gate.py` → **exit 0** ("pip-audit OK (1 known, all
  triaged in ALLOWED)" — the reviewed ecdsa PYSEC-2026-1325, no upstream
  fix); `scripts/check-dependency-namespaces.py` → exit 0.
- Vulture ledger with CI's exact arguments
  (`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`) → RC 0, 1238 reviewed identities = 1238 findings;
  this round changed no ledger row.
- `uv sync --locked --extra dev` → clean at the updated lock.
- `ruff check .` all passed; `ruff format --check .` 3562 files formatted.
- Container sandbox trio (`test_container_lane.py`,
  `test_container_sandbox.py`, `test_container_sandbox_hardening.py`) →
  **33 passed, 20 skipped** — identical to the recorded baseline (skips are
  the structural live-lane/platform gates documented in round 3).
- `check-suite-inventory.py --suite packages/maistro-bootstrap/tests` → ok,
  309 identities, no count change → no inventory-note delta required.
- `check-image-pins.py` → ok, 9 pins across 11 Dockerfiles, registry and
  tree hold each other closed at the new digest.
- `git diff --numstat origin/develop -- quality/` → only the intended branch
  rows (ac-state-notes append, image-inventory append, image-pins single-row
  re-record); no row loss.

## Residual risk

- The pin bump only re-opens the cache key chain once; a future DSA landing
  before the next bump re-creates the stale-assembly window. The header's
  re-bump doctrine (recorded per round in quality/image-pins.json) remains
  the maintenance model, and the Grype `--only-fixed` cross-check plus the
  scanned-target assertions above are the backstop.
- The temporalio bump is a lock move of a wheel the loop image installs but
  the repo never imports; `uv sync --frozen` inside the built image is the
  import-surface proof, and the fixture scan pins the advisory arithmetic.
- New advisories can land in any feed between this commit and CI's next
  evaluation; the gate policy (upgrade when a fix exists, triage only when
  none) applies unchanged.
