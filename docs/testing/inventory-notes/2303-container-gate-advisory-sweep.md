# Container-gate advisory sweep (#2303 CI repair)

No suite-count delta: no test was added, removed, renamed or skipped. One
existing test's pinned constant was updated in place
(`tests/test_distribution_contract.py::test_image_pins_supported_python_and_installs_identity`
now asserts `FROM python:3.13.18-slim-bookworm` where it asserted 3.13.16, so
the pin refresh cannot land without the test moving with it). No
`inventory-delta` block is recorded because no count moved.

## What changed and why

The #2303 merge-queue evaluation at d754936fea99 failed exactly one required
check, "Container scan + SBOM + cosign" (job 133166051159), and its visible
`npm audit` tail was a red herring: step #27, `RUN npm ci` in the
hive-conductor frontend stage, completed successfully (exit 0; reproduced
locally against the pinned `node:22-alpine` digest with identical output). The
actual failure chain, all of it fresh-advisory drift after develop's own
containers run passed, all of it fixed upstream:

1. Trivy (rsi-runner scan): `temporalio/bridge/Cargo.lock` (cargo) — `zip`
   8.6.0, CVE-2026-115905 (CRITICAL, fixed 9.0.5) / -907 / -908 / -909 (HIGH).
2. Grype (never reached in CI because 1 failed first): CVE-2026-115557
   (CRITICAL) in the CPython 3.12.15 / 3.13.16 interpreter binaries shipped by
   the digest-pinned `python` bases (fixed 3.12.16 / 3.13.18).
3. Grype (research image): node 24.21.0 bundled inside the playwright 1.64 /
   patchright 1.64 wheels — CVE-2026-111497 (CRITICAL) + CVE-2026-105482 /
   -105483 / -106069 (HIGH), fixed in node 24.22.1.

The repair moves dependencies and base pins; no ignore entry was added:

- `uv.lock`: temporalio 1.34.0 -> 1.36.1 (zip 9.5.1 in the bundled Cargo.lock;
  nexus-rpc 1.4.0 -> 1.5.0 moves with it), playwright 1.64.0 -> 1.65.2
  (driver node 26.13.1), patchright 1.64.1 -> 1.64.4 (driver node 24.22.1).
- `Dockerfile`, `packages/hive-conductor/Dockerfile`:
  python:3.13.16-slim-bookworm -> 3.13.18-slim-bookworm
  (sha256:a5a7017e…); `Dockerfile.research`, `Dockerfile.rsi-runner`,
  `packages/hive-conductor/tests/Dockerfile`, `deploy/sbx/template/Dockerfile.tests`:
  python:3.12-slim -> sha256:5e2bdb1b… (3.12.16). Recorded in
  `quality/image-pins.json`; `scripts/smoke-engine-canvas.sh`'s control image
  follows the 3.13.18 digest.
- The Conductor identity contract moves with the pin: the in-image assertion,
  both `security.yml` identity smokes, and
  `tests/test_distribution_contract.py` now assert (3, 13, 18).

## Test movement

- `tests/test_distribution_contract.py`: one constant, no count change.
- `uv run pytest tests/ -q`: 5909 passed, 140 skipped — same shape as before
  the change (no added/removed/skipped tests).
- `tests/test_pinned_digest_references.py` (14 cases incl.
  test_distribution_contract) all pass, holding the registry/smoke/Dockerfile
  pin closure closed across the refresh.
