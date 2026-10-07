---
inventory-delta:
  tests/: +13
---
# 611-release-publishes-scanned-digest

Issue #611 (#346 AC-5): the release must publish the digest that was
scanned, not a rebuild of it. `release.yml` now builds each published image
exactly once into its `-rc` quarantine repository, scans the candidate digest
with Trivy and Grype under security.yml's policy, applies the release tags to
the scanned digest via `docker buildx imagetools create` only after both
scans pass, and cosign-signs that same digest. `quality/image-inventory.json`
flips both `published_digest_verified` flags to `true` — and the +13
collected node IDs in `tests/` are the gate (`scripts/check-image-inventory.py`)
holding that claim to the wiring that makes it true:

- full wiring (build → trivy scan → `imagetools create` promote → `cosign
  sign`, all bound to `steps.<id>.outputs.digest`) passes with the flag
  `true`;
- `true` without a Trivy/Grype step consuming the built digest fails;
- `true` without an `imagetools create` applying the release tags to that
  digest fails — the original gap, where job names were the only evidence;
- `true` without a `cosign sign` of that digest fails (the signature would
  attest an artifact the release does not publish);
- `true` with the promote step placed before the scan step fails on ordering,
  because a finding at the gating severity must stop the publish, not
  correct it;
- `true` with the build itself tagging `:latest` or consuming the computed
  release-tag outputs fails — the build may only push to the quarantine;
- `true` with no `docker/build-push-action` push, a push step that declares
  no `id:` (nothing to bind a scan to), or a job with no steps at all fails;
- `false` still records the gap without demanding wiring (the honest state of
  an unwired release path), and a non-boolean flag fails;
- a real-tree test pins that both shipped PUBLISHED entries carry the claim
  and the gate's wiring read of the real `release.yml` holds — the test that
  fails if the release is rewired back to publish-before-scan without
  re-recording the claim.

The wiring is read from the workflow text (same line-anchor approach as the
gate's job parser, no YAML dependency), and the negative tests assert the
gate's actual failure text, so a reworded message cannot silently stop
describing the violation.
