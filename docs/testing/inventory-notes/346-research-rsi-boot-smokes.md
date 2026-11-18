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
