---
inventory-delta:
  tests/: +3
---

# Issue #2304 research image driver-node runtime swap

Round 9 of the #2304 container-gate repair: the gate's grype cross-check
flags the Node binaries bundled *inside the research image's venv* —
playwright 1.65.2 ships Node v26.13.1 and patchright 1.64.1 ships Node
v24.21.0 (both measured from the locked wheels with `--version`) — as
HIGH/CRITICAL surface in the published image (e.g. CVE-2026-111497
Critical and CVE-2026-105482/105483/106069 High on the v24.21.0 build,
fixed upstream in Node 24.22.1). The drivers are JavaScript launched
through Node, and both packages consult `PLAYWRIGHT_NODEJS_PATH` before
their bundled `driver/node`, so `Dockerfile.research` now installs a
checksum-verified system Node 24.22.1, points both drivers at it, and
deletes the bundled binaries and npm's vendored tree — keeping the
vulnerable binaries out of the shipped image rather than waiting on an
upstream driver release.

`tests/test_research_image_playwright_runtime.py` adds three tests: the
direct regression test (pinned tarball URL + expected sha256 literal +
`PLAYWRIGHT_NODEJS_PATH` override + both driver-node removals + npm prune
must all be present), the checksum-verification test (the downloader must
assert the tarball digest before extracting, matching the image's
hash-pinning posture), and the coupling test (playwright in `uv.lock`
implies the whole swap block exists, vacuously satisfied if playwright
ever leaves the lock). All three fail against the pre-round-9
`Dockerfile.research` (verified by running the module against a copy with
the swap block removed): the direct and coupling tests fail on the
missing markers, the checksum test on the absent fetch block.

Local proof on the rebuilt image (2026-11-16, head `89534e50` + comment
correction): full `docker build -f Dockerfile.research --no-cache-filter
production-apt` exit 0; trivy 0.73.0 (HIGH/CRITICAL, `--ignore-unfixed`,
repo `.trivyignore.yaml`) exit 0 with zero findings; grype 0.116.0
`--only-fixed --fail-on high` exit 0 — the node rows are gone; in-image
probes: `node --version` → v24.22.1 at `/usr/local/bin/node`, no
`driver/node` binaries left anywhere in the filesystem, npm tree absent,
and `playwright.sync_api` launches Chromium and navigates as the shipped
non-root user (uid 10001) through the system Node. Patchright's driver
likewise starts (its launch error is a pre-existing browser-revision gap —
revision 1248 was never downloaded by any round's `playwright install`;
no production code imports patchright).
