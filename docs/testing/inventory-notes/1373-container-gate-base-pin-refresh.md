---
inventory-delta:
  tests/: +0
---

# Container-gate base-pin refresh + lock floors (#1373 CI-repair round, 2026-11-16)

The "Container scan + SBOM + cosign" leg failed at this branch's head
4295a40c1 (security.yml run 43821935433, job 133146766062), one step later
than the b868e47f9 failure the previous repair commit (4295a40c1, docker
CLI rebuild) had cleared: all five image builds and the first two trivy
scans (hive-conductor, maistro-engine) passed, and the newly reached
"Trivy scan maistro-engine-research" step failed with 13 HIGH python-pkg
advisories in the research image's venv — oauthlib 4.0.0
(CVE-2026-49272), pyasn1 0.6.4 (CVE-2026-119194/195/196/197), pypdf
6.21.2 (CVE-2026-119203..119209), soupsieve 3.0.3 (CVE-2026-126190).
Every finding names a fixed version, so per this gate's standing policy
the repair is an upgrade, not a triage entry: `[tool.uv]
constraint-dependencies` floors (oauthlib>=4.0.1, pyasn1>=0.6.5,
pypdf>=6.21.4, soupsieve>=4.0 — trivy's "fixed in 4.0.0" is PEP
440-equal to PyPI's 4.0 release) plus the same treatment for the next
failure in line, proven the same way before it could burn another
merge-queue round:

- **grype leg (step 16, skipped at 4295a40c1)**: run locally with
  CI-exact arguments and grype 0.116.0 against a DB built 2026-11-15
  (fresher than any grype run this branch has had), it exits 2 on the
  research image: node 24.21.0 — the driver binary inside the
  patchright/playwright wheels — carries CVE-2026-111497 (CRITICAL, KEV,
  fixed 24.22.1) and HIGH CVE-2026-105482/105483/106069, and CPython
  3.12.15 carries CVE-2026-115557 (CRITICAL, fixed 3.12.16). Floors
  patchright>=1.64.4 (bundles node 24.22.1) and playwright>=1.65.2
  (bundles node 26.13.1; both verified by unpacking the wheels and
  running the bundled drivers), and the `python:3.12-slim` pin moves
  a0f57064… → 5e2bdb1b… (registry-reverified: now CPython 3.12.16) in
  `Dockerfile.research`, `Dockerfile.rsi-runner`,
  `packages/hive-conductor/tests/Dockerfile`,
  `deploy/sbx/template/Dockerfile.tests` and the
  `quality/image-pins.json` row.
- **rsi-runner trivy leg (step 15, also skipped at 4295a40c1)**: fails
  the same way locally on `temporalio`'s wheel-shipped
  `bridge/Cargo.lock` — zip 8.6.0, CVE-2026-115905 (CRITICAL, fixed
  9.0.5) + CVE-2026-115907/115908/115909 (HIGH). temporalio 1.36.1
  bundles zip 9.5.1 (verified by unpacking the wheel), so the direct
  root dependency floor moves to temporalio>=1.36.1.
- **hive-conductor/maistro-engine grype**: with the same fresh DB the
  identical CPython advisory CVE-2026-115557 fires on the
  `python:3.13.16-slim-bookworm` base (fixed in 3.13.18) — the exact
  class the #363 and #1152 refreshes document. The pin moves
  3.13.16/73aa5fae… → 3.13.18/a5a7017e… (registry-reverified) in
  `Dockerfile`, `packages/hive-conductor/Dockerfile`,
  `scripts/smoke-engine-canvas.sh` CONTROL_IMAGE and its
  `quality/image-pins.json` row; the in-Dockerfile identity stage assert
  and security.yml's two live `sys.version_info[:3]` checks follow to
  (3, 13, 18), as does the FROM-tag assertion in
  `tests/test_distribution_contract.py::test_image_pins_supported_python_and_installs_identity`
  (comment documents why). `tests/test_pinned_digest_references.py`
  needed no change: its contract (non-Dockerfile pin refs must match the
  registry verbatim) passes against the refreshed row — the refresh
  checklist it enforces is exactly what this round executed.

No test was added or removed, so recorded inventory counts are
unchanged (Hive 4,199 / Core 18,500, both re-verified against this
tree). The one modified assertion is in an unrecorded top-level suite
(`tests/`); the per-suite inventories gate does not cover it.

Local proof, all on this tree with the scanners pinned to CI's versions
(trivy 0.73.0 `--severity HIGH,CRITICAL --ignore-unfixed
--ignorefile .trivyignore.yaml`, grype 0.116.0 `--only-fixed
--fail-on high`, both with their current DBs):

| image | build | trivy | grype |
|---|---|---|---|
| hive-conductor:pr-cr1373 | 3.13.18 | exit 0 | exit 0 |
| hive-conductor-observability:pr-cr1373 | 3.13.18 | (not scanned by CI) | — |
| maistro-engine:pr-cr1373 | 3.13.18 | exit 0 | exit 0 |
| maistro-engine-research:pr-cr1373 | 3.12.16 | exit 0 | exit 0 |
| maistro-rsi-runner:pr-cr1373 | 3.12.16 | exit 0 | exit 0 |

security.yml's live verification commands pass against the rebuilt
images (`identity=operational python=3.13.18`,
`observability=importable identity=operational python=3.13.18`), and
the research image ships oauthlib 4.0.1 / pyasn1 0.6.5 / pypdf 7.1.0 /
soupsieve 4.1.1 / patchright 1.64.4 / playwright 1.65.2 with the
bs4→soupsieve CSS path exercised in-image.
