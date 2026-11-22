---
inventory-delta:
  tests/: +8
---

# Container-gate base-pin refresh + pip-audit floors (#891/#2238 CI repair)

The "Container scan + SBOM + cosign" leg failed at this branch's head
fd3a7ef18 (security.yml run, job 119987367064) at the step "Trivy scan
maistro-engine (HIGH/CRITICAL only)": trivy 0.73.0 flagged libexpat1
2.5.0-1+deb12u4 (CVE-2025-59375, CVE-2026-77214, HIGH, fixed
2.5.0-1+deb12u5) in the maistro-engine image. A rebuild of the same
Dockerfile outside CI installs deb12u5 and scans clean. The difference is
the buildx gha cache: the engine image's `apt-get upgrade` layer is keyed on
the pinned base digest, so once cached it never re-runs, and a Debian
security fix published after the cache was written never reaches the image.

The repair refreshes the `python:3.13.16-slim-bookworm` pin (a1165e27… →
73aa5fae…, same tag, same bookworm 12.15 suite, same CPython 3.13.16, apt
candidate libexpat1 2.5.0-1+deb12u5 — all re-verified live from the
registry) in `Dockerfile` (builder + runtime),
`packages/hive-conductor/Dockerfile` (pybuild + runtime),
`scripts/smoke-engine-canvas.sh` CONTROL_IMAGE and the
`quality/image-pins.json` row; the base-digest bump invalidates the stale
cached layer, and the rebuilt image upgrades libexpat1 to deb12u5. The
trixie-based `python:3.12-slim` pin is deliberately untouched: the deb12u*
advisories do not apply to it, and the newer tag resolution would be a
Debian 13 suite migration no gate evidence asks for. The same repair shape
was applied on the #2209 and #1152 branches the same day; this branch
carries its own copy because the gha cache is per-branch.

`tests/test_pinned_digest_references.py` is new: 8 node IDs. The refresh had
to update `scripts/smoke-engine-canvas.sh`'s canvas-less CONTROL_IMAGE by
hand alongside the Dockerfiles, because `check-image-pins.py` closes the
registry against Dockerfiles only — a refresh that misses a non-Dockerfile
reference ships silently, and the control probe then verifies the smoke
against a base the image under test no longer uses. The suite scans every
registered non-Dockerfile reference surface for `name:tag@sha256:<digest>`
refs and requires each to be registered verbatim in
`quality/image-pins.json`; it requires the control image to resolve to a pin
row some Dockerfile actually builds from; it rejects a stale digest of a
registered image:tag (the exact failure mode of this refresh); and it pins
the scanner's shape (bare/unpinned/malformed references are not its
problem). No existing test was removed or renamed.

The same round floors two dev-only transitive advisories for the
"Supply chain (pip-audit)" leg (gitpython>=3.2.1, graphql-core>=3.3.0 in
`[tool.uv] constraint-dependencies`, following the aiohttp precedent);
that change adds no tests, so it contributes no delta here.
