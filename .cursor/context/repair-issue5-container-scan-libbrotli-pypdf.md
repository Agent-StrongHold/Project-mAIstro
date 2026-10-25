# Issue #5 (MILESTONE M1) — lane auto-5 CI-repair: "Container scan + SBOM + cosign" (job 07cd6155)

Phase: repair. Starting head `8b9a60d5b9a8` (branch auto-5), develop base `4de7e906d9dc`
(origin/develop still == base at repair time; no sync conflict to resolve).

## Failure reproduced from CI logs (job 120781851142, run 40063516081)

Failing step: **Trivy scan maistro-engine-research (HIGH/CRITICAL only)** — exit 1.
Findings (trivy 0.73.0, `ignore-unfixed`, table from the runner log):

- `libbrotli1` CVE-2026-111497 (HIGH, brotli decoder OOB write), installed
  `1.1.0-2+b7`, fixed `1.1.0-2+deb13u1` (trixie-security)
- `pypdf` CVE-2026-115572 / CVE-2026-115580 / CVE-2026-115585 (HIGH ×3),
  installed `6.21.1`, fixed `6.21.2`

The research image is trixie-based (`python:3.12-slim@sha256:a6e34…` → debian
13.7); the bookworm-based hive-conductor/maistro-engine scans passed in the
same job. The rsi-runner trivy step never ran (job aborted first), but it is
the same trixie + libcurl surface.

## Repair (salvaged uncommitted work from the prior run, completed and verified)

- `Dockerfile.research`: `production-apt` stage now names `libbrotli1`
  explicitly, so the fixed trixie-security candidate is an install
  requirement of the stage CI re-runs every candidate
  (`--no-cache-filter production-apt`).
- `Dockerfile.rsi-runner`: same explicit `libbrotli1` in `runtime-apt`.
- `uv.lock`: pypdf 6.21.1 → 6.21.2 (`uv lock --check` clean; hashes updated).

## Local proof (docker 29.1.3, trivy 0.73.0 = the action's pinned version)

| Gate / step (CI-exact where possible) | Result |
|---|---|
| `docker build` production-apt stage → `dpkg -s libbrotli1` | `1.1.0-2+deb13u1` |
| Full `maistro-engine-research` rebuild (buildx, `--no-cache-filter production-apt`, `--load`) + trivy 0.73.0 `--severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed --ignorefile .trivyignore.yaml` | **exit 0** (debian 13.7: 0 findings) |
| Final image dpkg / importlib.metadata | libbrotli1 `1.1.0-2+deb13u1`, pypdf `6.21.2` |
| Full `maistro-rsi-runner` rebuild + same trivy invocation | **exit 0**, and dpkg libbrotli1 `1.1.0-2+deb13u1` |
| `check-image-lock-reconciliation.py` vs research image (CI-exact args) | OK: 148 dists, exit 0 |
| `check-image-lock-reconciliation.py` vs rsi-runner image (CI-exact args) | OK: 220 dists, exit 0 |
| `uv export --locked --package maistro-server --extra observability --extra browser` | `pypdf==6.21.2` (via browser-use) |
| `uv sync --locked --extra dev`; `uv lock --check` | clean |
| `ruff check .` / `ruff format --check .` | pass / 3484 files formatted |
| `check-image-pins.py` | 8 pins across 10 Dockerfiles, exit 0 |
| `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1302 → 1302, exit 0 (no Python changed, ledger untouched) |
| pytest: image/pin/build-context/license/retry test files (test_image_lock_contract, test_check_build_context, test_prepull_base_images, test_prepull_copy_sources, test_dependency_namespaces, test_distribution_contract, test_check_image_inventory, test_buildx_build_retry, test_check_image_lock_reconciliation) | 311 passed |
| pytest: test_check_image_pins, test_check_license_inventory, test_ci_merge_group_outputs, test_engine_canvas_packaging | 128 passed, 3 skipped |

## Residual risk

The CI runner's production-apt stage log shows it already *fetched*
libbrotli1 `1.1.0-2+deb13u1` while the scanned image reported `1.1.0-2+b7`
installed — i.e. the scanned artifact did not match the freshly re-run stage,
the signature of the GHA build-cache replay that `--no-cache-filter` (#795)
exists to bound. The explicit install requirement plus the per-candidate stage
re-run is the same mechanism that fixed the libexpat1 case; if CI's cache
replays a stale downstream chain again, the gate fails visibly (as it did
here) rather than silently passing. pypdf flows from uv.lock, so it does not
depend on apt cache state at all.

No ledger/grant edits (vulture scan matches the committed baseline). No test
additions → no suite-inventory delta. Issue #5's milestone-level exit
conditions remain owned by the #446 child issues, unchanged by this repair.
