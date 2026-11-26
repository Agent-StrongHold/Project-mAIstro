# Container-gate base-pin refresh (#859 / PR #2209; delta superseded)

This note records no inventory delta after the develop sync. The eight
`tests/test_pinned_digest_references.py` nodes are already counted by
[1152-container-gate-base-pin-refresh.md](1152-container-gate-base-pin-refresh.md),
inherited from develop. At `048727437`, the test file and the pin changes below
are identical to develop `b9cd15c60`; retaining both `tests/: +8` entries made
`check-suite-inventory.py --suite tests/` expect 5,819 nodes while collecting
5,811. Withdraw only this duplicate delta, preserving the historical repair
record below and the genuine `tests/: +1` in
[859-restore-drill-readiness-pin.md](859-restore-drill-readiness-pin.md).
No test is removed or weakened.

The "Container scan + SBOM + cosign" leg failed on PR #2209 (run
39805852418, job 119918729666): trivy flagged libexpat1 2.5.0-1+deb12u4
(CVE-2025-59375, CVE-2026-77214, HIGH, fixed 2.5.0-1+deb12u5) in the
maistro-engine image. The image's `apt-get upgrade` layer was served from the
buildx gha cache — frozen before the deb12u5 fix was published — while the
hive-conductor image's identical layer re-ran fresh in the same job and
scanned clean. The repair refreshes the `python:3.13.16-slim-bookworm` pin
(a1165e27… → 73aa5fae…, same tag, same bookworm 12.15 suite, same CPython
3.13.16) in `Dockerfile`, `packages/hive-conductor/Dockerfile`,
`scripts/smoke-engine-canvas.sh` and `quality/image-pins.json`; the base
digest bump invalidates the stale cached layer, and the rebuilt images
install deb12u5 and scan 0 HIGH/CRITICAL. The trixie-based
`python:3.12-slim` pin is deliberately untouched: the deb12u* advisories do
not apply to it, and the newer tag resolution is a Debian 13 suite migration
that no gate evidence asks for.

`tests/test_pinned_digest_references.py` is new: 8 node IDs. The repair had
to update `scripts/smoke-engine-canvas.sh`'s canvas-less CONTROL_IMAGE by
hand alongside the Dockerfiles, because `check-image-pins.py` closes the
registry against Dockerfiles only — a refresh that misses a non-Dockerfile
reference ships silently, and the control probe then verifies the smoke
against a base the image under test no longer uses. The suite scans every
registered non-Dockerfile reference surface for `name:tag@sha256:<digest>`
refs and requires each to be registered verbatim; it requires the control
image to resolve to a pin row some Dockerfile actually builds from; it
rejects a stale digest of a registered image:tag (the exact #2209 failure
mode, demonstrated against the pre-repair line); and it pins the scanner's
shape (bare/unpinned/malformed references are not its problem). No existing
test was removed or renamed.
