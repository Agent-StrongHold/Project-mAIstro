# #2303 digest-pull and harness-build verification (5b967946b1)

No suite-count delta: no test was added, removed, renamed or skipped by this
round. This is a verification-only round over the already-committed repair
series; the note records independent acceptance evidence for the issue's
actual content — the `mcr.microsoft.com/playwright v1.64.1-noble`
`7852dc5…` → `47b510d…` digest refresh in
`packages/hive-conductor/tests/Dockerfile.playwright` +
`quality/image-pins.json`.

## Why a further round existed

The two immediately preceding rounds (`db8abe6d`, `1d27b144`, `f24877a4`,
`7797ebbc`) all died on **model-provider infrastructure errors** (provider
finish_reason error / 400 "missing tags"), not on gate or code failures —
their driver check logs (`check-*.log`) show `uv sync`, `ruff check`, and
`ruff format --check` all exit 0 on this exact head. The worktree was already
clean at the expected head, so nothing needed salvaging; this round's only job
was to prove acceptance against reachable production behavior.

## CI state at this head (API snapshot, captured 2026-11-17T04:44Z)

All 78 check-runs on `5b967946b12eb38965659cb3ed6520f5fe58d1ad` conclude
`success` — including the previously red gates: **Container scan + SBOM +
cosign**, **Coverage gate (publish-set floor + diff coverage)**, **Quality
gate (Pillars 1–4, 7, 8)**, **Quality / Image pins**, **test**,
**exact-debt-ledger**, **hive-conductor-e2e-ui** (which builds and drives the
bumped image), **docker-build**, and **docker-rebuild-compare**. The PR
reports `mergeable: true` against `157c3f615b` (the develop merge is already
inside the branch).

## Independent local acceptance evidence

| Check | Command | Result |
| --- | --- | --- |
| Pinned index digest resolves | `docker manifest inspect mcr.microsoft.com/playwright@sha256:47b510dd9230bf0b9bfc9b20102241e577ea7a99334ab4c3ca19f19770e9b8ea` | 2-arch index: linux/amd64 → `d65108d1…`, linux/arm64 → `969a9e36…` — byte-for-byte the per-arch move recorded in the `quality/image-pins.json` note |
| Digest is pullable | `docker pull mcr.microsoft.com/playwright@sha256:47b510d…` | exit 0, digest confirmed |
| Harness image builds | `docker build -f tests/Dockerfile.playwright .` (in `packages/hive-conductor`) | exit 0 |
| Harness functions | `docker run --rm … npx playwright --version` | `Version 1.64.1` (matches the `@playwright/test@1.64.1` build-time pin and the base tag) |
| Every spec import resolves in the image | `docker run --rm … npx playwright test --config=tests/e2e/playwright.config.ts --list` | `Total: 246 tests in 47 files`, no collection errors |
| Image pins gate | `RATCHET_BASE_REV=origin/develop uv run python scripts/check-image-pins.py` | `9 pinned base/tool image(s) across 10 Dockerfile(s)` |
| Image inventory gate | `uv run python scripts/check-image-inventory.py` | 9 Dockerfile(s) dispositioned |
| Vulture ratchet (CI's exact args) | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1238 reviewed identities → 1238 findings, exit 0 |
| DevSkim scope guard | `uv run pytest tests/test_devskim_scan_scope.py -q` | 21 passed |
| Suite inventory | `PATH=.venv/bin:$PATH python3 scripts/check-suite-inventory.py` | 21 suites match (35384 node IDs) — note: bare `python3` (system interpreter, no pydantic) fails collection for two hive-conductor suites; CI's job runs with the synced environment |
| Driver battery | `uv sync --locked --extra dev`, `uv run ruff check .`, `uv run ruff format --check .` | all exit 0 (job `26758c5a` check-0/1/2.log) |

## Residual risks

- The `gates-ran` aggregate status was still `pending` in the API snapshot
  even with all 78 check-runs green; that is GitHub-side status-rollup timing,
  not a gate this branch can fix.
- The heavy container-scan steps (Trivy/Grype/SBOM/cosign, lock
  reconciliation) were re-proven by CI's green run on this head, not locally
  rebuilt; local evidence covers the digest chain, image build, and harness
  function instead.
