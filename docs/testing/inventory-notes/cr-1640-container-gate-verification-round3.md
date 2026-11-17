# CR-1640: container-gate verification at the final head (round 3)

Verification record, no suite delta. Head `c6261a9b96` (branch
`chatgpt/1629-acceptance-delivery-planner` after merging develop's
M2-B1 `f927334a2e`, which moved `uv.lock`, `quality/image-pins.json`
and the sandbox packages); develop base `a660bc2a9d0`.

Why a third round: the merge-queue evaluation that reported
"Container scan + SBOM + cosign: failure" predated this head. Round 2
(`cr-1640-container-gate-reverification.md`) proved the gate at
`b4f644367d`, i.e. before the M2-B1 merge changed image inputs again,
and left grype-on-research/rsi-runner, the lock reconciliations, the
live version asserts and the SBOM/license inventory unproven locally.

CI evidence at this exact head (verified via
`gh api .../actions/runs/44022092973`: `head_sha == c6261a9b96`):
the `security` workflow's "Container scan + SBOM + cosign" job
completed SUCCESS at 2026-11-17T05:32:47Z, and the PR rollup at this
head is green for every named gate (test, Quality, coverage,
exact-debt-ledger, devskim, mutation, lint-and-type-check).

Local reproduction at this head (WSL docker daemon healthy; all five
images rebuilt from `c6261a9b96` with CI's `--no-cache-filter` args):

- Builds: `hive-conductor:pr-cr1640-verify`,
  `hive-conductor-observability:pr-cr1640-verify`,
  `maistro-engine:pr-cr1640-verify`,
  `maistro-engine-research:pr-cr1640-verify`,
  `maistro-rsi-runner:pr-cr1640-verify` — all OK.
- Version/identity asserts (CI's exact one-liners): both Conductor
  images report python 3.13.18, bip-utils 2.12.2, coincurve 21.0.0,
  pynacl 1.6.2; observability additionally imports opentelemetry +
  OTLP exporter. RC=0 both.
- Trivy `--severity HIGH,CRITICAL --ignore-unfixed --ignorefile
  .trivyignore.yaml --exit-code 1`: RC=0 on all four scanned images.
- Grype `--fail-on high --only-fixed`: RC=0 on all four. The research
  image initially failed with `no space left on device` in
  stereoscope's `/tmp` cache (tmpfs at 93%); rerun with `TMPDIR` on a
  roomier filesystem passed with zero matched findings —
  infrastructure, not the gate.
- Reconcile installed packages to uv.lock (CI's exact four
  invocations incl. `--member` asserts): "ships exactly the locked
  set" for maistro-engine (126 dists), hive-conductor (73),
  maistro-engine-research (147), maistro-rsi-runner (220). RC=0 x4.
- Frontend license surfaces rebuilt from scratch (`npm ci` + `npm run
  build` in both frontends), then syft SBOMs for the four images plus
  the four directory surfaces and
  `scripts/check-license-inventory.py`: "OK: inventoried 8
  surface(s), 25292 component(s); copyleft=419 (policy=review)". RC=0.
- Cosign: signing is removed by design (`.github/workflows/security.yml`
  documents the removal; no signing step to verify).

Supporting gates re-run at this head:
`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` RC=0 (1236 == 1236 identities);
`scripts/check-suite-inventory.py` RC=0 (21 suites match);
`uv run pytest tests/test_plan_delivery.py -q` 56 passed — matching
the reconciled +54/+2 split between the delivery-planner and
reservation-scope notes.
