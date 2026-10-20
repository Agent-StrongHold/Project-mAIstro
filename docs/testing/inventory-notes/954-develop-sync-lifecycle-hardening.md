---
inventory-delta:
  packages/maistro-core/tests: +0
---

# #954 develop-sync round — lifecycle hardening carried across the #952 merge

This round resolved the develop sync conflict on `auto-954`: upstream's #952
registry persistence (PR #1988: `InstallRecord`, `ExtensionInstallStore`,
`SqliteExtensionInstallStore`, `verify`, CLI read surface) landed in
`maistro.extensions` alongside the B2/B3 lifecycle implementation
(`ExtensionInstallRecord`, `ExtensionStore`, the `service` state machine). The
two halves are name-disjoint except one deliberate rename: the lifecycle's
operator-asserted evidence is now `OperatorTrustEvidence`, so the durable #952
`TrustEvidence` keeps the name develop already shipped. Suite count impact of
the merge itself is zero (upstream's +41 is already in the recorded baseline
via `952-extension-install-records.md`).

## Second develop sync (420d503d4, this round): salvage superseded, delta zeroed

The second develop sync (history-rewritten develop tip `420d503d4`) brought
develop's own evolved B3 implementation for the same files this lane had
drafted (TrustClaim, `ExtensionStore` protocol, health/catalog services,
`pinned_record`, expired-authorization sweep). The sync resolution takes
develop's side for every conflicted path, which supersedes the +3 salvage
tests this note previously carried; their delta is now **+0**:

- `test_install_lifecycle.py::TestRemovedVersionBytesStayAnchored` (2) —
  dropped: develop's `_reinspection_outcome` treats terminal records
  (including REMOVED) as non-gating, so a removed `(scope, extension,
  version)` key may be re-inspected with different bytes. The stricter
  removed-version byte anchoring the draft enforced is not part of develop's
  semantics; the draft tests are preserved in history at `139018eb5` and in
  the merge parents, not in this tree.
- `test_post_install_lifecycle.py::TestRollback::test_later_activations_preserve_the_original_installer`
  (1) — dropped: develop's service attributes `installed_by` at install time
  and names later operators on the transition trail; the first-installer
  freeze the draft implemented is not develop's contract.

The branch-only HTTP surface file
`packages/maistro-server/tests/api/test_extensions_lifecycle_api.py` (13
cases, declared +13 by the pre-sync draft of
`954-extension-post-install-lifecycle.md`) tested draft-only routes
(`/pins`, `/upgrades`, `/resolution`, `/reconciliation`) that develop's
canonical API replaces with `/installations/{id}/pin|unpin|resume|remove`,
`/rollback` and the transitions audit endpoint; it is removed with this
round. Every behavior it pinned over HTTP is pinned by develop's
`test_extensions_api.py::TestPostInstallLifecycleHttp` against the live
routes.

Net inventory effect of this round: `packages/maistro-core/tests` +0,
`packages/maistro-server/tests` −13 relative to the pre-sync branch tree,
both accounted by the union of notes now in the tree (develop's
`954-extension-post-install-lifecycle.md` declares the canonical suite).
