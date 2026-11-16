---
inventory-delta:
  tests/: +0
---
# CR-1640: containers-gate grype failure on the research image's bundled Node

Suite: `tests/`
Delta: +0 collected cases. The regression is locked by extending the existing
`test_research_ships_the_locked_browser_stack_above_the_security_floors` in
`tests/test_distribution_contract.py` with one new floor entry in
`BROWSER_SECURITY_FLOORS` (`patchright: 1.64.4`); no test functions added,
removed, renamed, skipped or weakened, so the recorded per-suite counts are
unchanged (verified: `python scripts/check-suite-inventory.py` OK at 21 suites).

Root cause (CI run 43857650421, job 133265946717, head `4b5a4f065419`): the
containers gate's `Grype scan (cross-check)` step failed on
`maistro-engine-research:pr-1640` with node 24.21.0 binary findings —
CVE-2026-111497 (Critical, KEV), CVE-2026-105482/105483/106069 (High) — all
fixed only in node 24.22.1. Every trivy leg had already passed, so the job died
before the SBOM/license/reconcile/sign legs.

Provenance of the vulnerable binary: the research image installs the `browser`
extra, whose `browser-use 0.5.9` depends on `patchright`; the
`patchright==1.64.1` wheel bundles its own Node.js runtime at
`patchright/driver/node`, verified locally to be v24.21.0 (extracted from the
PyPI wheel and executed). The playwright 1.65.2 wheel bundles v26.13.1, so
patchright's driver was the only vulnerable node in the image.

Fix: `uv lock --upgrade-package patchright` moves the lock to
`patchright==1.64.4` — the first release verified to bundle node v24.22.1
(wheel extracted and executed locally). Only patchright moves in the lock. The
floor is then enforced by the distribution contract, which reads the committed
lock and the shipped `uv export --locked` projection, so a downgrade below the
advisory-floor release fails `test_distribution_contract.py`; the floor was
confirmed to fire against the regression version (1.64.1 below 1.64.4) with a
doctored lock copy outside the worktree.

Local proof at the fixed head, CI-exact tooling and arguments:

- `docker buildx build --load -f Dockerfile.research -t
  maistro-engine-research:pr-1640 --no-cache-filter production-apt .` → rc=0
  (builder smoke: `import maistro_server.main` passes; `--require-hashes`
  locked install passes).
- In-image: `patchright/driver/node --version` → v24.22.1;
  patchright 1.64.4, playwright 1.65.2, browser-use 0.5.9.
- `grype maistro-engine-research:pr-1640 --fail-on high --only-fixed` (grype
  0.116.0, the pinned CI version) → rc=0; only Medium/Low/Unknown rows remain
  (python 3.12.16 binary Mediums, otel go-module Mediums, GO-2026-6859
  Unknown) — the same non-blocking rows the other three images carry.
- `trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1
  --ignorefile .trivyignore.yaml maistro-engine-research:pr-1640` (trivy
  0.73.0, the pinned CI version) → rc=0.
- Reconciliation leg: `uv export --locked --package maistro-server --extra
  observability --extra browser --no-dev --no-emit-workspace` +
  `scripts/check-image-lock-reconciliation.py --image
  maistro-engine-research:pr-1640` → rc=0 (147 distributions, export names
  `patchright==1.64.4`).
- `uv sync --locked --all-extras` + `uv pip freeze` + `pip-audit --strict
  --format=json` + `scripts/pip_audit_gate.py` → gate rc=0 (only the reviewed
  `ecdsa==0.19.2 PYSEC-2026-1325` triage; patchright 1.64.4 carries no
  advisories).
- `uv lock --check` OK; `ruff check .` and `ruff format --check .` clean;
  `pytest tests/test_plan_delivery.py tests/test_distribution_contract.py
  tests/test_check_image_lock_reconciliation.py tests/test_check_image_pins.py
  tests/test_pinned_digest_references.py` → 191 passed.

Scope: the other three images cannot be affected — only `Dockerfile.research`
selects the `browser` extra (engine: `--extra image`; hive-conductor: no
browser extra; rsi-runner: `--extra rsi-fitness`), and CI's grype passed all
three at this head.

Not locally executed (never ran in CI either, because grype failed first):
syft SBOMs, `check-license-inventory.py`, cosign. No npm tree or license-class
input changes with this fix (package-lock files untouched); those legs remain
pending CI at the next pushed head.
