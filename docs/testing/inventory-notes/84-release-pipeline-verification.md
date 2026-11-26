---
inventory-delta:
  tests/: +14
---
# Release pipeline verification and in-place repair (#84)

Verifies the existing release workflows end-to-end at the assigned develop
base `799b9a27` instead of recreating them, and repairs the two gaps the
exercise actually found. This note records the writer-executed acceptance
sweep plus the two repairs; the job manifest carried no `check-*.log` files,
so every check below was executed first-party at this head.

## Repairs (actual gaps found by exercising the pipeline)

1. **Publish-set metadata failed the release's own `twine check --strict`
   gate.** Building the six-package publish set (`PUBLISH_SET` in
   `release.yml`'s wheels job) at this commit and running the workflow's
   literal gate (`uv tool run --from twine twine check --strict dist/*`)
   failed 8 of 12 artifacts: `maistro-canvas`, `maistro-evolve`,
   `maistro-ext-sdk` and `maistro-rsi` shipped no `long_description`
   (no declared readme). At tag time this fails the `wheels` job and blocks
   the whole release. Repair: truthful READMEs for canvas/evolve/rsi,
   `readme = "README.md"` in those plus maistro-ext-sdk's pyproject (the SDK
   already had a README it never declared). Gate now passes 12/12.

2. **`get.sh` never verified install.sh by default.**
   `verify_installer_checksum` was opt-in only (`MAISTRO_SHA256SUMS_URL` unset
   meant silent skip), so the default `curl | bash` path consumed none of the
   checksum evidence `release.yml` attaches. Repair: `resolve_ref()` defaults
   `MAISTRO_SHA256SUMS_URL` to the tagged release's own
   `releases/download/<tag>/SHA256SUMS` asset, making verification the default
   for every tagged install (fail-closed on mismatch/missing manifest) while
   preserving the explicit override and the no-manifest branch-install
   behavior. get.ps1 needs no change: it delegates to get.sh inside WSL and
   forwards an explicit override.

## Writer-executed acceptance evidence (at 799b9a27)

- `actionlint 1.7.7` (with shellcheck) over `release.yml` +
  `release-installer.yml`: clean; YAML parses; job DAG guard → m1-closeout →
  {wheels → pypi, images} → github-release; release-installer publishes
  nothing (its old second publish path is gone — ADR-073126-c4e1 §3 holds).
- wheels job steps run verbatim at this commit: `uv build` all six publish
  packages (sdist+wheel each, all at VERSION 0.9.0), filename/count check 6=6,
  `scripts/verify-wheel-imports.py` clean-venv import for all six: pass.
- `scripts/release_guard.py`: unit tests pass (24); for a well-formed
  `v0.9.0-rc1` it outputs `prerelease=true`, `target_branch=develop`
  (ADR-095-amended mapping already at base), and passes once a `## [0.9.0]`
  CHANGELOG section is cut — failing before that is the designed
  notes-exist gate, verified by running both sides.
- `bump_version.py --check`: 42 sites agree on 0.9.0;
  `check-release-consistency.py --releasing v0.9.0-rc1`: ok.
- RC isolation read from the workflow source: prerelease ⇒ moving
  `latest`/`X.Y` image pointers withheld (guard `pointers` step), images
  promote only the immutable tag into the production repos from the scanned
  `-rc` quarantine digest, PyPI goes to TestPyPI (`skip-existing`), GitHub
  release is `--prerelease` without `--latest`.
- External verification surface: release notes embed `sha256sum --check
  --ignore-missing SHA256SUMS` plus the anchored `cosign verify`
  identity/issuer commands matching the workflow's own verify step; the
  images job verifies the signatures in-run and checks provenance
  attestations against the Dockerfile base pins.

## Explicitly UNVERIFIED here (needs live GitHub/registry infrastructure)

Actually pushing an RC tag, the `release` environment approval, PyPI/TestPyPI
trusted publishing, ghcr pushes and keyless cosign signatures — all documented
maintainer prerequisites at the bottom of `release.yml`; this lane may not
mutate GitHub. The release-installer compose-stack smoke (smoke-linux) and the
image build/scan/promotion steps likewise need hosted runners/ghcr.

## Suite delta

Two test files under `tests/` (+7 and +3 cases): the get.sh checksum
verification contract (default-on tag verification, fail-closed modes,
override and branch behavior) and the publish-set readme metadata contract
(parsed from the workflow's own PUBLISH_SET). Package README/pyproject edits
move no test counts.
