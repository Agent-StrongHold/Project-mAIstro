---
inventory-delta:
  tests/: +4
---

# Research + rsi-runner boot smokes ported onto develop images (#346 gap (b))

Adds `tests/test_image_boot_smokes.py` (4 tests) holding the two #346 gap-(b)
boot smokes to their contracts: ci.yml's docker-build job still invokes
`scripts/smoke-research-chromium.sh` and `scripts/smoke-rsi-runner-imports.sh`
against the images it just built; the rsi smoke's `PACKAGE_PATHS` equals the
operator contract's in `tools/run_rsi_isolated.sh`; and each smoke's
digest-pinned control image is the base its own Dockerfile builds from.
`tests/test_pinned_digest_references.py` gains the two scripts as registered
pinned-reference surfaces (no count change — edit only).

## CI-repair round (2026-11-18, this branch)

No suite-count change. The four red gates on the 2026-11-04 PR runs were
diagnosed and repaired in-tree; inventory impact is zero everywhere:

- security + Supply chain (pip-audit): manifest floors + lock moves for
  graphql-core/joserfc (CVE-2026-119286/119284) and the research-venv set,
  carried in from the validated #2389 repair (same base commit). No test
  change.
- Container scan + SBOM + cosign: docker/cli v29.9.3 + x/net patch in both
  Dockerfiles' `dockerclibuild` stage; temporalio floored at 1.36.1 (vendored
  zip 9.5.1) for the rsi-runner leg. No test change.
- Coverage gate: `tests/test_devskim_scan_scope.py` now parses devskim.yml
  once per test instead of once per shipped file (lru_cache on the three
  workflow-reading helpers). Test count unchanged (21 in that file); every
  assertion byte-identical; the sweep still demands `excluded == []` over all
  1648 files. This was the gate's actual failure (pytest-timeout >30s inside
  yaml.safe_load, job 126407866791), not a coverage regression.

## Develop-sync round (2026-11-21, this branch)

No suite-count change anywhere (`tests/: +4` above still holds). The branch
was merged onto develop through 469f361339 and then origin/develop
(a3efc93c92); the sync surfaced exactly two places where the branch's smokes
drifted from develop's evolved Dockerfiles, both repaired and held by the
suite this note already records:

- Control-image digest refresh: develop refreshed the shared
  `python:3.12-slim` base to `sha256:5e2bdb1b…` (3.12.16, #2120 round), so
  both smokes' default `CONTROL_IMAGE` now pin that digest — exactly the
  same-commit-refresh rule `tests/test_pinned_digest_references.py` enforces;
  `test_research_control_image_is_the_dockerfiles_own_base` and
  `test_rsi_control_image_is_the_dockerfiles_own_base` failed on the stale
  `a0f57064…` pin and pass after the refresh.
- `_first_from` → `_python_base_from` in `tests/test_image_boot_smokes.py`:
  develop's `node-driver-patch` stage now precedes the python builder in
  Dockerfile.research, so "first FROM" no longer names the artifact's runtime
  base. The helper now takes the first `FROM python:` line — still
  digest-pinned, still the base the probe's interpreter runs on, still
  cross-checked against the smoke script's pin. The node stage is a transient
  toolchain layer, not the control's referent; no assertion weakened.

Conflict resolution provenance: the two merges hit pyproject.toml, uv.lock,
both Dockerfiles and the devskim test; every hunk was comment- or
specifier-list-only, resolved to the union of both repair rounds (branch's
PR #2389 provenance + develop's CR1373/#1450 provenance) — `uv lock --check`
passes, `git diff origin/develop -- Dockerfile Dockerfile.research
pyproject.toml` contains comment lines only, and the lock's pypdf 7.1.1 /
soupsieve 4.1.2 (this branch's 2026-11-18 resolve, both above the CVE
floors) satisfy `uv lock --check` against the merged manifests.
