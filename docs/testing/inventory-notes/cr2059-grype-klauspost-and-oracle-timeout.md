---
inventory-delta:
  tests/: +3
---
# cr2059-grype-klauspost-and-oracle-timeout

Repair round for #2059 on `fix/vulture-single-owner-1357` (start head
`625879d0`). Two gates were red at that head (runs 43878191747 / 43878205511,
2026-11-16); everything else — all Quality/*, exact-debt-ledger, Vulture
Ratchet — passed on hosted CI.

## 1. "Container scan + SBOM + cosign" — Grype cross-check (deterministic)

Job 133336745388 failed at step 16, "Grype scan (cross-check)" (`--fail-on
high --only-fixed`), on `maistro-engine:pr-2059`:

- GO-2026-6865 (High, fixed 1.20.2) in `github.com/klauspost/compress` v1.20.1,
  part of docker/cli's vendored module set inside the source-built
  `/usr/local/bin/docker`. This is the only High-severity row; the remaining
  rows (otel GHSA-q7gw-24fr-5p69 Medium, go stdlib GO-2026-6859 Unknown,
  CPython-binary Medium/Low) sit below `--fail-on high`.

Fix: both Dockerfiles that build the CLI (`Dockerfile`,
`Dockerfile.research`) add `github.com/klauspost/compress@v1.20.2` to the
stage's `go get` (after the go-jose/x/net bumps of the previous round, still
followed by `go mod vendor`).

Test: `tests/test_docker_cli_vendored_advisory_floors.py` +2 cases —
`test_docker_cli_stage_raises_klauspost_compress_to_fixed_release` per
Dockerfile. Fails against the pre-fix Dockerfiles for the intended reason.

Local proof: the `dockerclibuild` stage was built at this head and
`go version -m /out/docker` inside it shows
`github.com/klauspost/compress v1.20.2` (plus go-jose v4.1.6, x/net v0.62.0)
— the exact module rows Grype reads from that binary.

## 2. "Coverage gate (publish-set floor + diff coverage)" — combine step (flake with a real brittleness)

Job 133345309671 failed at step 7, "combine": all four
`tests/test_restore_oracle_characterization.py` tests errored at fixture
setup with `Failed: Timeout (>30.0s) from pytest-timeout` while
`docker run` created the `pgvector/pgvector:pg17` container (image pull on a
loaded runner). The parallel instance of the same job on the same head
passed — the root producer's `--timeout=30` cannot contain this module's
setup: one image pull plus `_wait_ready`, which is allowed 90s by design.
The prior round's CPython bump did not cause this; it is the same class the
readiness-gate repair (#1881 follow-up) already recorded for this module.

Fix: `tests/test_restore_oracle_characterization.py` carries
`pytest.mark.timeout(300)` at module level (one pull + two readiness cycles),
which overrides the producer flag for this module only.

Test: `tests/test_restore_oracle_readiness_gate.py` +1 case —
`test_characterization_module_budgets_beyond_the_producers_30s_default`,
a no-Docker structural pin that the module's effective timeout exceeds the
30s producer default and covers two `_READY_TIMEOUT_S` windows. Fails
against the pre-fix module (no timeout mark) for the intended reason.

## Net inventory delta

`tests/: +3` (2 in `test_docker_cli_vendored_advisory_floors.py`, 1 in
`test_restore_oracle_readiness_gate.py`). No suite removed or renamed.

## Residual risks (recorded, not repaired here)

- The Grype loop order is hive-conductor -> engine -> research -> rsi-runner;
  this run aborted at engine, so research/rsi-runner were not re-scanned at
  this head. Their Trivy legs passed earlier in the same job, and the prior
  rounds raised their known floors (uv.lock pins; temporalio zip).
- `go stdlib GO-2026-6859 (Unknown, fixed go1.27.4)` remains below the fail
  threshold with the 1.27.3-alpine builder; it only becomes actionable if a
  future advisory on the same toolchain crosses High.
