---
inventory-delta:
  tests/: +2
---

# Issue #2304 research image playwright/libatomic runtime dependency

Round 8 of the #2304 container-gate repair: the advisory lock bumps landed in
round 7 moved playwright 1.64.0 -> 1.65.2, and the 1.65.2 bundled Node driver
(v26.13.1) links `libatomic.so.1` where the 1.64.0 driver did not (verified
with `ldd` against both wheels). `Dockerfile.research`'s `production-apt`
stage names `libatomic1` explicitly — the same "installed explicitly, not
left to dependency resolution" posture as its libbrotli1 entry — so
`python -m playwright install chromium` no longer dies with exit 127
("error while loading shared libraries: libatomic.so.1") before the browser
downloads. That failing step is what red `Container scan + SBOM + cosign`
(job 133267675340) and `docker-build` (job 133270207586) at head `094944a81`;
`integration-scope` (job 133267675417) is purely downstream of docker-build.

`tests/test_research_image_playwright_runtime.py` adds two tests: the direct
regression test (the production-apt apt list must name `libatomic1`) and the
coupling test (playwright present in `uv.lock` implies `libatomic1` in the
stage, vacuously satisfied if playwright ever leaves the lock). The first
test fails against the pre-fix Dockerfile — the exact state that shipped the
CI exit-127 build failures — because the pre-fix apt closure has no
libatomic1.

Local proof on the rebuilt image (`docker build -f Dockerfile.research`):
the previously failing step downloads Chromium 159.0.8154.6 / FFmpeg /
headless shell and the image exports; `playwright/driver/node --version`
executes (v26.13.1); Trivy 0.73.0 (HIGH/CRITICAL, ignore-unfixed, repo
`.trivyignore.yaml`) exits 0 with zero findings; the gate's own
`check-image-lock-reconciliation.py` step passes (147 distributions = the
locked set). The same build/scan/reconciliation battery passes for a locally
rebuilt `hive-conductor` image (73 distributions; its OS base moved to
`python:3.15.2-slim-bookworm` and its venv to CPython 3.13.18 in round 7
without a completed scan in CI).
