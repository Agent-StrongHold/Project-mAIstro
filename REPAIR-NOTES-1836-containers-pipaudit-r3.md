# REPAIR-NOTES-1836 — containers + pip-audit CI-gate repair round 3 (branch auto-1836, salvage of the rate-limit-aborted attempt)

Assigned block at dispatch: `security = failure`, `Supply chain (pip-audit) =
failure`, `Container scan + SBOM + cosign = failure` (check-runs at head
`ae1a239da929`). The prior writer attempt produced the full repair diff but
died on a provider 429 before committing it (`jobs/6eeb.../result.json`,
`failure_kind: rate_limited`). This round salvaged that uncommitted diff
verbatim, re-derived every root cause from the failing runs' own logs, and
proved each fix locally. No gate was weakened; no ignore entry was added.

## 1. Failure evidence, read from the three failing jobs (read-only `gh api`)

- **Supply chain (pip-audit)** (job 133050526368) and **security** (job
  133048756616, run 43790845718): `pip_audit_gate.py` rejected four advisories
  outside the triaged allowlist:
  `dnspython==2.9.0 CVE-2026-128089 -> 2.9.2`,
  `graphql-core==3.3.0 CVE-2026-119286 -> 3.3.1`,
  `joserfc==1.7.5 CVE-2026-119284 -> 1.7.6`,
  `opentelemetry-api==1.45.1 CVE-2026-126360 -> 1.45.2`.
  (The "produced no usable report" lines in the log digest are the retry
  loop's `bash -x` trace echo, not an executed error — both jobs report
  `pip-audit attempt 1: report complete (audit exit 1)`.)
- **Container scan + SBOM + cosign** (job 133050526425, run 43790845602):
  died at the *maistro-engine* trivy step (the hive-conductor scan before it
  passed; the grype/SBOM/cosign legs never ran). Findings: `dnspython 2.9.0
  CVE-2026-128089 HIGH` (python-pkg) and two gobinary HIGHs in the image's
  built docker CLI — `go-jose/v4 v4.1.5 CVE-2026-116587 (fixed 4.1.6)` and
  `golang.org/x/net v0.60.0 CVE-2026-78661 (fixed 0.62.0)`. The rsi-runner
  security-patch stamp step PASSED in this run (log line:
  `security-patch stamp: 43790845602 (run 43790845602)`); the "stale
  build-cache binding" string in the digest is likewise a trace echo.
- **grype leg (never reached in CI this run):** the prior round measured
  grype 0.116.0 flagging CPython 3.13.16 binary `CVE-2026-115557 CRITICAL`
  (fixed 3.13.18) on the locally rebuilt engine image — the same mechanism
  that drove the #363 refresh. That is why the base pin moves to 3.13.18
  beyond the dnspython fix.

## 2. The salvaged repair (all verified, not re-derived)

- `quality/image-pins.json` + `Dockerfile` + `packages/hive-conductor/Dockerfile`
  + `security.yml` identity assertions + `scripts/smoke-engine-canvas.sh` +
  `tests/test_distribution_contract.py` +
  `docs/security/CONDUCTOR-IDENTITY-SUPPORT-MATRIX.md`:
  `python:3.13.16-slim-bookworm@sha256:73aa5fae…` →
  `python:3.13.18-slim-bookworm@sha256:a5a7017e…`.
  Pin verified upstream this round: `docker buildx imagetools inspect
  python:3.13.18-slim-bookworm` returns exactly digest `sha256:a5a7017e…`.
- `Dockerfile` + `Dockerfile.research` docker/cli stage:
  `v29.9.1 (dfc520d)` → `v29.10.0-rc.2 (eaae503)`. Verified upstream this
  round: `git ls-remote` peels `refs/tags/v29.10.0-rc.2^{}` to
  `eaae503a22566c…` (matches the pinned short commit), and the tag's
  `vendor.mod` vendors `go-jose/v4 v4.1.7` + `x/net v0.62.0` (both ≥ the
  fixed versions), while v29.9.1's vendors the vulnerable pair. v29.9.3
  still vendors x/net v0.60.0 (same check), so no stable tag carries both
  fixes — an RC tag of an exact upstream ref is the minimal move, and the
  in-build commit assertion keeps it immutable.
- `uv.lock`: dnspython 2.9.2, graphql-core 3.3.2, joserfc 1.8.0,
  opentelemetry-api/-sdk 1.45.2, otel semconv 0.66b2 (+ pyobjc marker
  simplification and the `revision = 3` this machine's uv 0.12.20 writes;
  `uv lock --check` passes and CI's `uv sync --locked` reads older
  revisions, so freshness — which is manifest-based — is unaffected).

## 3. Local proof (this round, true exit codes)

- CI-exact pip-audit battery: `uv sync --locked --all-extras`;
  `uv pip freeze --exclude-editable`; `uv run pip-audit --strict
  --format=json -r …` → only `ecdsa 0.19.2 PYSEC-2026-1325` (reported twice
  in the report) remains, the sole ALLOWED pair;
  `uv run python scripts/pip_audit_gate.py <report>` → **rc 0**.
- `docker buildx build -f Dockerfile -t maistro-engine:pr-2264
  --no-cache-filter runtime-apt --load .` → rc 0; in-image assertions:
  `python 3.13.18`, `dnspython 2.9.2`,
  `Docker version v29.10.0-rc.2, build eaae503`; the dockerclibuild stage
  cloned `v29.10.0-rc.2` and asserted short commit `eaae503`.
- CI-exact trivy on that image (`trivy 0.73.0`, `--severity HIGH,CRITICAL
  --exit-code 1 --ignore-unfixed --ignorefile .trivyignore.yaml`,
  current DB) → **rc 0**, 0 HIGH/CRITICAL.
- CI-exact grype cross-check on that image (`grype 0.116.0`, `--fail-on
  high --only-fixed`) → **rc 0**; the CPython CRITICAL is gone; remaining
  rows are Medium/Low/Unknown (below the fail threshold).
- CI-exact lock reconciliation: `uv export --locked --package
  maistro-server --extra image …` + `check-image-lock-reconciliation.py
  --image maistro-engine:pr-2264 …` → **rc 0** ("ships exactly the locked
  set").
- `uv run pytest tests/test_distribution_contract.py -q` → 6 passed.
- `uv run python scripts/check-image-pins.py` → rc 0;
  `scripts/check-image-inventory.py` → rc 0;
  `scripts/check-workflow-inventory.py` → rc 0;
  `scripts/check-suite-inventory.py --suite tests/` → rc 0 (no test
  added/moved — the changed test keeps its count, so no inventory note is
  owed);
- CI-exact vulture (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`) → rc 0, 1238 reviewed == 1238 findings: no ledger
  amendment owed, `quality/vulture-baseline.json` untouched.
- The issue's deterministic acceptance command:
  `uv run python scripts/check-adr-status-language.py && git diff --check`
  → rc 0 / rc 0.
- SPEC-101826-1836 golden vectors V-1 … V-18 re-executed independently
  against the production helper and the documented recipes: 40/40 checks
  pass (bytes, digest, reordered maps, all eleven mutations, both V-14
  pairs, all eight V-15 rejections with the documented messages, both V-16
  collisions, the V-17 ensure_ascii pin, and the V-18 legacy row through
  inline recipe, production `approval_request_digest`, and the
  `DurableApproval` fallback).

## 4. Decision-gate posture (unchanged, by design)

SPEC-101826-1836 stays `status: Proposed`, `contracts: []`: the ADR owner's
explicit acceptance of the payload contract is the issue's real gate and
remains open. Nothing in this repair touches the contract, its vectors, or
its evidence; no implementation is claimed.

## 5. Residual risks

- hive-conductor / research / rsi-runner images were not rebuilt locally this
  round (engine was, as the exact failing image). Their pins verify upstream;
  hive-conductor's trivy leg passed even on 3.13.16, and the bump only
  refreshes its content; CI re-runs the full battery.
- grype flags `GO-2026-6859` (go1.27.3 stdlib, fixed `*1.27.4`, severity
  Unknown) below the fail threshold — a future watch item for the golang
  builder pin, not this repair.
- cosign/SBOM steps need CI secrets and are not locally reproducible; they
  run after the now-green scans.
