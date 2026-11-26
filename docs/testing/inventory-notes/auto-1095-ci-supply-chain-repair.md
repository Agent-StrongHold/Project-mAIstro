# auto-1095-ci-supply-chain-repair

CI-repair round for the three failing hosted checks at `b352beaa2`
(`security`, `Supply chain (pip-audit)`, `Container scan + SBOM + cosign`).
No test files were added, removed, or renamed; suite inventories are
unchanged and re-verified by `scripts/check-suite-inventory.py`.

## Root causes (both trunk-level, reproduced locally)

1. **pip-audit advisories against the locked dependency set.** The worktree
   `uv.lock` is byte-identical to the develop merge base for dependencies,
   and a local run of the CI-exact gate failed identically:
   `gitpython==3.1.62 CVE-2026-114145` (fixed 3.2.1) and
   `graphql-core==3.2.11 CVE-2026-75507/75508` (fixed 3.2.12/3.3.0rc1).
   Both packages are dev-only transitives (`gitpython` via cosmic-ray,
   `graphql-core` via moto) but pip-audit gates the whole frozen
   environment. Fix: `uv lock --upgrade-package gitpython
   --upgrade-package graphql-core` → 3.2.1 / 3.3.0.
2. **Go stdlib CVE in self-built binaries.** The `security` job log for the
   failing run shows the first Trivy scan (hive-conductor) failing on
   `usr/bin/age` and `usr/bin/age-keygen`: CVE-2026-111943 (HIGH, crypto/x509
   MITM via untrusted intermediate certificates), stdlib go1.27.2, fixed in
   go1.26.10/1.27.3. All three Go-build stages pinned
   `golang:1.27.2-alpine@sha256:f92b6ef8…`. Fix: bump the pin to
   `golang:1.27.3-alpine@sha256:b8c9b82a…` (index digest resolved via
   `docker buildx imagetools inspect`) in `Dockerfile`,
   `Dockerfile.research`, `packages/hive-conductor/Dockerfile`, and record
   it in `quality/image-pins.json` (#363 entry updated, recorded_in #1095).

## Local proof (CI-exact commands)

- `uv sync --locked --extra dev` + `uv pip install pip-audit` + freeze +
  `pip-audit --strict` + `scripts/pip_audit_gate.py` → exit 0 (only the
  triaged `ecdsa` PYSEC-2026-1325 pair remains, allowed).
- Same gate against `uv sync --locked --all-extras` (security.yml's
  supply-chain job) → exit 0.
- `scripts/check-image-pins.py` → 8 pins across 10 Dockerfiles, all
  registered (exit 0).
- Rebuilt all four images locally; on each, Trivy v0.73.0
  `--severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed --ignorefile
  .trivyignore.yaml` → exit 0, and `grype --fail-on high --only-fixed` →
  exit 0. The rebuilt rsi-runner carries gitpython 3.2.1 / graphql-core
  3.3.0; the rebuilt hive-conductor still passes the CI identity-contract
  run (python 3.13.16, bip-utils 2.12.1, coincurve 21.0.0, pynacl 1.6.2).
- Regression battery unchanged: ruff check/format clean; the seven
  `packages/maistro-server/tests/api` suites the driver runs → 152 passed;
  mutation-toolchain tests (`tests/test_mutation_*`) → 87 passed, 4
  skipped; `check-suite-inventory.py` → ok; `check-vulture-baseline.py`
  (CI-exact args) → 1314 reviewed identities == 1314 findings.
