---
inventory-delta:
  tests/: +8
---

# Container-gate base-pin refresh (#1152)

The "Container scan + SBOM + cosign" leg failed at this branch's head
4c6e21712 (security.yml run 39823108438, job 119979244278): trivy 0.73.0
flagged libexpat1 2.5.0-1+deb12u4 (CVE-2025-59375, CVE-2026-77214, HIGH,
fixed 2.5.0-1+deb12u5) in the maistro-engine image, while a rebuild of the
same Dockerfile outside CI installs deb12u5 and scans clean. The difference
is the buildx gha cache: the engine image's `apt-get upgrade` layer is keyed
on the pinned base digest, so once cached it never re-runs, and a Debian
security fix published after the cache was written never reaches the image.
The repair refreshes the `python:3.13.16-slim-bookworm` pin (a1165e27… →
73aa5fae…, same tag, same bookworm 12.15 suite, same CPython 3.13.16 — both
re-verified live from the registry) in `Dockerfile` (builder + runtime),
`packages/hive-conductor/Dockerfile` (pybuild + runtime),
`scripts/smoke-engine-canvas.sh` CONTROL_IMAGE and the
`quality/image-pins.json` row; the base-digest bump invalidates the stale
cached layer, and the rebuilt images upgrade libexpat1 to deb12u5 and scan
0 HIGH/CRITICAL. The trixie-based `python:3.12-slim` pin is deliberately
untouched: the deb12u* advisories do not apply to it, and the newer tag
resolution is a Debian 13 suite migration that no gate evidence asks for.

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
registered image:tag (the exact failure mode of this refresh, demonstrated
against the pre-repair line); and it pins the scanner's shape
(bare/unpinned/malformed references are not its problem). No existing test
was removed or renamed.
