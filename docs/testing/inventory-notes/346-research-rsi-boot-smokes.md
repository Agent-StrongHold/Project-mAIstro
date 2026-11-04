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
