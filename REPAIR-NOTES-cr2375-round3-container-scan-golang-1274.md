# CR-2375 round 3 — Container scan + SBOM + cosign gate repair (Go builder 1.27.3 -> 1.27.4)

Branch: `dependabot/docker/templates/autonoetic/python-3.15.0-slim-bookworm`.
Round start head: `42ea88cdd651` (round 2's develop-sync merge). All round-2 work
(develop sync resolution, picomatch waiver retirement, npm-audit gate tests)
carried in untouched.

## CI failure diagnosed (not guessed)

security.yml run 44477475371, job 135401410021 ("Container scan + SBOM + cosign",
head 42ea88cdd651), failed at the FIRST Trivy step (`Trivy scan (HIGH/CRITICAL
only)`, image-ref `hive-conductor:pr-2375`) 7m45s in, before any later step ran:

```
usr/bin/age-keygen (gobinary)
Total: 1 (HIGH: 1, CRITICAL: 0)
│ stdlib │ CVE-2026-97054 │ HIGH │ fixed │ v1.27.3 │ 1.26.11, 1.27.4 │
```

One finding: the Go stdlib embedded in the `age`/`age-keygen` static binaries.
The `agebuild` stage (`packages/hive-conductor/Dockerfile`) builds age v1.3.1
from source on `golang:1.27.3-alpine@sha256:b8c9b82…` (the #1152 pin), and Go
1.27.3's stdlib now carries CVE-2026-97054 (net/http MaxBytesReader connection
handling, HIGH, fixed in go1.26.11/1.27.4). This is the documented recurring
class in `quality/image-pins.json` (prebuilt 1.25.x -> 1.27.2 rebuild ->
1.27.3 rebuild, each aged out by the next stdlib advisory). The root
`Dockerfile` / `Dockerfile.research` `dockerclibuild` stages pin the same
1.27.3 toolchain (the #2414 re-serialized index `fa3d596…`), so their docker
CLI binaries embed the same vulnerable stdlib even though the job failed
before their scans ran — all three pins move together.

## Fix (gate policy: upgrade when a fix exists, never ignore)

- `packages/hive-conductor/Dockerfile` agebuild, `Dockerfile` and
  `Dockerfile.research` dockerclibuild: re-pinned to
  `golang:1.27.4-alpine@sha256:70bd7ddea8b6cbe5d6943cde279d6b67feb10cc924fb9100d1d8757c1575b280`
  with the CVE chain documented in each header comment.
- `quality/image-pins.json`: the two golang 1.27.3-alpine rows (#1152
  `b8c9b82…`, #2414 `fa3d596…`) retired into one 1.27.4-alpine row used by all
  three Dockerfiles, note carrying the full chain and resolution evidence.

Digest resolution, 2026-11-19: `docker buildx imagetools inspect
golang:1.27.4-alpine` -> OCI index `sha256:70bd7dde…` (created 2026-11-10,
linux/amd64 child `ea30e256…`, base `alpine:3.24`), verified live by running
the pinned digest: `go version go1.27.4 linux/amd64` on Alpine 3.24.4.

## Local proof (trivy v0.73.0 — CI's exact version, DB updated 2026-11-18)

- Both build stages rebuilt with the new pin:
  `go version -m` reads `go1.27.4` for `/out/age`, `/out/age-keygen` (age
  v1.3.1, tag commit b8564ad check intact) and `/out/docker` (docker/cli
  v29.9.3, x/net 0.62.0 + compress 1.20.2 patches intact).
- `trivy rootfs --severity HIGH,CRITICAL --ignore-unfixed` on the extracted
  binaries: age 0, age-keygen 0, docker 0.
- **Full hive-conductor image rebuilt from this branch** (frontend + agebuild
  + pybuild + runtime stages) and scanned with CI's exact step arguments
  (`trivy image --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed
  --ignorefile .trivyignore.yaml --vuln-type os,library`): **exit 0**, zero
  HIGH/CRITICAL across os/library/gobinary targets.
- CI's runtime step reproduced on the rebuilt image: identity contract
  prints `identity=operational python=3.13.18 bip-utils=2.12.2
  coincurve=21.0.0 pynacl=1.6.2`.

## Gate battery at round end (all green)

- `check-image-pins.py`: 10 pins across 11 Dockerfiles, all registered.
- `check-image-inventory.py`, `check-build-context.py`,
  `check-workflow-inventory.py`, `check-workflow-write-safety.py`: OK.
- `pytest tests/test_check_image_pins.py tests/test_pinned_digest_references.py
  tests/test_check_image_inventory.py tests/test_prepull_base_images.py
  tests/test_image_lock_contract.py tests/test_check_image_lock_reconciliation.py
  tests/test_install_docker_sock.py` — 243 passed.
- `pytest tests/test_npm_audit_gate.py` — 15 passed (round-2 surface intact).
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (CI-exact args, baseline read from merge base):
  1235 = 1235.
- `ruff check .` / `ruff format --check .`: clean.
- `check-suite-inventory.py`: 21 suites match (no tests added; no delta note).
- `git merge-tree --write-tree origin/develop HEAD`: exit 0, no conflicts.

No `.trivyignore.yaml` edit: the ignore stays limited to its named findings,
and this CVE has a released fix, so the upgrade is the gate-conformant path.
