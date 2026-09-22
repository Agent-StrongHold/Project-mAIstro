---
inventory-delta:
  tests/: +76
---

# Issue #362 compliance registry gate

Adds root tests covering registry schema validation, explicit statuses,
immutable evidence requirements, release-digest fail-closed behavior, disabled,
manual-only, or stale evidence, evidence scope and GitHub artifact provenance,
commit-bound workflow locator resolution, test-reference shape,
release-required unverified controls, the no-tag evidence workflow, and
malformed or drifting COMPLIANCE.md table rows.

The repair batch adds: mandatory `expires` on every `implemented`,
`partially_implemented`, or `documented` claim (a null expiry can never go
stale, so it fails closed), attestation content and artifact-provenance failure
paths, commit-bound artifact resolution failures, GitHub API failure handling,
workflow-state derivation failures, registry/evidence schema failure tables,
document structure and drift rejections, checker and producer `main` exit
codes, and producer fail-closed behavior for subprocess failures or empty test
lists.
