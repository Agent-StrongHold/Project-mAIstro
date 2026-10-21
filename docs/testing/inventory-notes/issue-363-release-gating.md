---
inventory-delta:
  tests/: +7
---
# Issue #363: fail closed before release promotion; retain license evidence

Seven new root cases:

- Two execute the release license / promotion shell steps in workflow order,
  with scanner transport failure or genuinely unknown metadata. The real
  license gate runs; neither failure may apply release tags.
- One executes successful scan and promotion blocks, verifies quarantine digest
  scans and extraction from the installed Conductor bundle, reconciles component
  references, and opens the evidence archive (raw SBOMs, report, policy).
- One checks matching artifact download/upload wiring, executes release staging
  and `gh release create` with a recording stub, and verifies both inventory
  assets are in SHA256SUMS and the release upload arguments.
- Two require release staging to fail when either license evidence asset is
  absent; there must be no checksum manifest for an incomplete release.
- One pins the research image's post-browser-use Pillow security floor and
  PEP-440/import assertion. Actual build + scanner validation is recorded in
  `REPAIR-NOTES-363-release-gating.md`.

Workflow tests stub only external npm/scanner/registry commands. They execute
production shell blocks, the actual license CLI, tar, and sha256sum. These are
not claims that a remote release has been published or signed.
