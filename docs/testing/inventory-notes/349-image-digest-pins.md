---
inventory-delta:
  tests/: +16
---
# 349-image-digest-pins

Issue #349 pins every base/tool image reference in the repository's nine
Dockerfiles by immutable digest and adds the gate that keeps them pinned. The
+16 collected node IDs in `tests/` are `tests/test_check_image_pins.py`, which
holds `scripts/check-image-pins.py` to its contract:

- `:latest` is rejected everywhere — explicit (`python:latest`) and implicit
  (a bare image name), including a `:latest` tag that is technically immutable
  because a digest rides along (that is not a reviewable version annotation);
- an unpinned base fails in a release-scope Dockerfile (PUBLISHED/DISTRIBUTED
  per `quality/image-inventory.json`) and needs an owned, issue-numbered
  exemption even in an INTERNAL one — mirroring the inventory gate's coverage
  exceptions;
- every digest pin must be registered in `quality/image-pins.json` with the
  exact image, tag and digest, and every registration must name exactly the
  Dockerfiles that use it (`used_by` drift and unused rows both fail), so a
  base update can only land as a reviewable registry-plus-Dockerfile change;
- stage references (`FROM builder`, `COPY --from=0`) are not external images;
- `--base-digests` enumerates the pinned refs (release.yml's provenance check
  consumes this) and refuses unpinned ones;
- `--verify-attestation` proves a cosign-downloaded SLSA attestation names
  every pinned base digest, fails when one is missing, and fails loudly on
  input that is not cosign output — never vacuously.

The negative tests assert on the gate's actual failure text, so a reworded
message cannot silently stop describing the violation.
