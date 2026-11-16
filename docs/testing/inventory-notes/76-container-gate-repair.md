---
inventory-delta: {}
---

# Issue 76 container-gate repair (CI-repair round, 2026-11-16)

No test counts changed: the only test edit updates the asserted interpreter
tag in `tests/test_distribution_contract.py` (3.13.16 -> 3.13.18) to match the
refreshed base-image pin. This note records the CI-repair evidence for the
"Container scan + SBOM + cosign" gate.

## Failing gate (GitHub run 43822789023, job 133149494061, head ca35d2d7)

Step outline (fetched via `gh run view`): every "Build ..." step and the first
Trivy scan (hive-conductor) passed; **"Trivy scan maistro-engine
(HIGH/CRITICAL only)" failed** with exactly two findings in
`usr/local/bin/docker` (gobinary):

- CVE-2026-116587 — github.com/go-jose/go-jose/v4 v4.1.5, fixed v4.1.6 (HIGH,
  DoS via crafted RSA parameters in JWKs)
- CVE-2026-78661 — golang.org/x/net v0.60.0, fixed v0.62.0 (HIGH, DoS via
  crafted HTML input)

(The `npm audit` lines in earlier findings were tail noise from the successful
hive-conductor frontend build, not the failure.)

## Fix under review (uncommitted salvage, re-validated locally)

1. `Dockerfile` + `Dockerfile.research` dockerclibuild stage: patch the
   v29.9.1 release tag's vendored tree with
   `go get github.com/go-jose/go-jose/v4@v4.1.6 golang.org/x/net@v0.62.0
   github.com/klauspost/compress@v1.20.2 && go mod vendor` (same
   patch-the-release-tag policy the file already applies to the Go toolchain).
2. Base-image digest refreshes recorded in `quality/image-pins.json`:
   python:3.13.16-slim-bookworm -> 3.13.18 (grype Critical CVE-2026-115557 in
   the CPython binary, fixed 3.13.18) and python:3.12-slim -> 3.12.16 (same
   Critical, fixed 3.12.16), propagated to the version assertions in
   `packages/hive-conductor/Dockerfile`, `.github/workflows/security.yml`, and
   `scripts/smoke-engine-canvas.sh`.
3. `uv.lock` transitive bumps (none imported by `packages/*/src` — verified by
   grep) resolving fresh PyPI advisories.

## Local re-execution evidence (this host, 2026-11-16)

- `docker build --no-cache -f Dockerfile --target dockerclibuild` — exit 0:
  the patched vendored tree builds (`go get` + `go mod vendor` + `go build`),
  binary reports `Docker version v29.9.1, build dfc520d`.
- `docker build -f Dockerfile -t maistro-engine:pr-2241` — exit 0; runtime
  python reports 3.13.18.
- trivy v0.73.0, fresh DB (2026-11-16), CI flags `--severity HIGH,CRITICAL
  --ignore-unfixed --exit-code 1 --ignorefile .trivyignore.yaml` — all four
  gate images, all exit 0: **maistro-engine** (`usr/local/bin/docker
  gobinary  0` findings), **hive-conductor**,
  **maistro-engine-research**, **maistro-rsi-runner**.
- grype v0.116.0 (checksum-verified), `--fail-on high --only-fixed` — all
  four gate images, all exit 0: maistro-engine, hive-conductor (built exit 0
  with the in-image `(3, 13, 18)` identity assert; the workflow's
  identity-contract step was re-run verbatim and printed
  `identity=operational python=3.13.18 ...`), maistro-engine-research,
  maistro-rsi-runner.
- `scripts/check-image-lock-reconciliation.py` re-run verbatim against the
  locally built maistro-engine (new uv.lock export vs image contents):
  `OK: maistro-engine:pr-2241 ships exactly the locked set (126
  distributions, incl. 3 workspace member(s))`, exit 0.
- Old python:3.12-slim digest vs new: grype flags CPython 3.12.15
  CVE-2026-115557 **Critical** (fixed *3.12.16); the new digest resolves
  Python 3.12.16 and no longer carries it. zlib1g Highs (CVE-2026-76844 /
  CVE-2026-85091, fixed only in trixie deb13u1) pre-exist on BOTH base digests
  and are resolved by the images' `apt-get upgrade` stages (same
  trixie-security doctrine already documented in `.trivyignore.yaml` for
  libbrotli1).
- `uv sync --locked --all-extras` + pip-audit `--strict` +
  `scripts/pip_audit_gate.py`: gate exit 0 (only the already-triaged
  `ecdsa==0.19.2 PYSEC-2026-1325`).
- `uv lock --check`: consistent. `uv run ruff check .` /
  `ruff format --check .`: clean. `uv run pytest
  tests/test_distribution_contract.py`: 6 passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: exit 0 (1238 reviewed
  identities -> 1236 findings, no unbanked rows).
