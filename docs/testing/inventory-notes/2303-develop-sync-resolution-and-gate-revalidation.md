# #2303 develop sync (157c3f6) resolution and gate revalidation

No suite-count delta: no test was added, removed, renamed or skipped by this
round. The merge brought develop's M1-E2 (#1373) tests into the branch and
develop's own inventory notes came with them; `scripts/check-suite-inventory.py`
passes on the merged tree (21 suites, 35384 node IDs, 0 duplicate identities).

## What this round did

The worktree carried an in-progress, fully staged but **uncommitted**
`git merge origin/develop` (MERGE_HEAD 157c3f615b, the M1-E2 durable-runs
convergence) — the "develop sync conflict preserved in worktree" block. This
round audited the staged resolution, repaired one mangled file, and committed
the merge.

- All code/lock paths resolved to develop's side (verified per-file blob hashes
  against both parents): M1-E2 durable-runs convergence, docker CLI v29.9.3
  (5457199) with the patched x/net approach superseding this branch's retired
  v29.10.0-rc.2 attempt in `Dockerfile`/`Dockerfile.research`, and `uv.lock`
  already identical on both sides (temporalio 1.36.1, playwright 1.65.2,
  patchright 1.64.4).
- `quality/image-pins.json` was the one broken resolution: the two `python`
  rows had lost `tag`/`digest`/`recorded`/`recorded_in`/`note`, which would
  fail `scripts/check-image-pins.py` against the still-referenced
  `python:3.13.18-slim-bookworm@sha256:a5a7017e…` and
  `python:3.12-slim@sha256:5e2bdb1b…` FROM lines. Both parents carry the
  identical digests for those rows, so the file was rebuilt as develop's rows
  (trunk provenance) plus this branch's only real change: the
  `mcr.microsoft.com/playwright v1.64.1-noble` `7852dc5…` → `47b510d…` refresh
  (the issue's content). Post-repair the file differs from develop in exactly
  that row.
- `rsi-polling-resilience.spec.ts` keeps this branch's bounded-boundary deflake
  (documented in `2303-rsi-backoff-bound-slop.md`).

## Gates executed locally on the merged tree (2a98a6a601)

| Gate (CI args) | Result |
| --- | --- |
| `uv sync --locked --extra dev` then `--all-extras` + maistro-evolve (quality-mypy's env) | clean |
| `uv run ruff check .` | clean |
| `uv run ruff format --check .` | clean (3562 files) |
| `uv run python scripts/check-image-pins.py` | 9 pins / 10 Dockerfiles, all registered |
| `uv run python scripts/check-suite-inventory.py` | 21 suites match, 35384 node IDs |
| `uv run mypy --strict packages/maistro-core/src` | Success: 839 files |
| `pytest tests/test_check_image_pins.py tests/test_pinned_digest_references.py tests/test_devskim_scan_scope.py tests/test_distribution_contract.py` | 73 passed |
| `scripts/check-doc-links.py`, `check-release-consistency.py`, `check-radon-baseline.py`, `check-workflow-inventory.py`, `check-backlog-consistency.py` | all pass |

## Issue acceptance (playwright digest bump)

- `packages/hive-conductor/tests/Dockerfile.playwright` FROMs
  `mcr.microsoft.com/playwright:v1.64.1-noble@sha256:47b510dd9230bf0b9bfc9b20102241e577ea7a99334ab4c3ca19f19770e9b8ea`;
  the pins row matches exactly and no stale `7852dc5` reference remains
  anywhere in the tree (only the historical mention inside the sweep note).
- The digest resolves upstream right now (`docker buildx imagetools inspect`):
  OCI index `47b510d…` with linux/amd64 child `d65108d1…` and linux/arm64
  child `969a9e36…` — exactly the per-arch move the pin note records.
- `@playwright/test@1.64.1` stays pinned at build time in the harness; only the
  base image layers moved.

## Container gate (the round's named red gate) — input-equivalence evidence

`security.yml`'s "Container scan + SBOM + cosign" builds and scans five images:
hive-conductor, hive-conductor-observability (both `packages/hive-conductor/Dockerfile`),
maistro-engine (`Dockerfile`), maistro-engine-research (`Dockerfile.research`),
maistro-rsi-runner (`Dockerfile.rsi-runner`). It does **not** build or scan the
playwright e2e image this PR bumps. On the merged tree every one of those
inputs — all five Dockerfiles, `uv.lock`, `pyproject.toml`, `.trivyignore.yaml`,
the workflow itself — is byte-identical to origin/develop (verified by the
per-file resolution audit; the branch's only change to a scanned Dockerfile is
a 3-line comment addition in `packages/hive-conductor/Dockerfile`). develop's
own merge-queue run passed this same gate on these identical inputs after the
#1373 CI repair. Artifact-level spot checks on this worktree confirm the
repair claims: temporalio 1.36.1's vendored `bridge/Cargo.lock` ships zip
9.5.1 (the CRITICAL/HIGH zip advisories fixed ≥ 9.0.x), and the refreshed base
digests match the FROM lines (image-pins gate). The npm-audit tail in the
d754936 failure log was previously reproduced as exit 0 (red herring); the
blocking findings were the rsi-runner Trivy zip advisories and the Grype
CPython/node advisories, all addressed upstream by the lock/pin state above.

## Residual risks

- Full buildx + Trivy/Grype/cosign re-execution was not run locally (45-minute
  CI job, cold cache); the verdict rests on input-equivalence with develop's
  green run plus the artifact-level checks above.
- The e2e playwright suite (23 tests) is inventory-validated only; execution
  needs the full CI stack. The branch's deflake note covers the observed
  failure mode.
