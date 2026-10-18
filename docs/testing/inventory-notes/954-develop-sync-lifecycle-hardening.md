---
inventory-delta:
  packages/maistro-core/tests: +3
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

**+3 `packages/maistro-core/tests/extensions/`** — carried salvage from the
crashed prior attempt, completed and validated here:

- `test_install_lifecycle.py::TestRemovedVersionBytesStayAnchored` (2) — a
  removed version's digests stay anchored: reinstalling a different payload
  under the same semver is refused (`InspectionConflict`, and no candidate
  record is created); the identical artifact reopens a fresh authorization
  track (new `install_id`, `AWAITING_AUTHORIZATION`, loader called once per
  install). Pins #954's remove/reinstall semantics against the identity rule
  the #952 registry layer enforces on its own records.
- `test_post_install_lifecycle.py::TestRollback::test_later_activations_preserve_the_original_installer`
  (1) — `installed_by` stays the first installer across resume and rollback;
  later operators are attributed on the transition trail only. Fixed in this
  round: the salvaged draft re-installed the already-ACTIVE v1.4.0 via
  `install_then_upgrade`, which idempotent re-inspection correctly returns
  as-is; the test now upgrades the live v1 to 1.5.0 and rolls back, matching
  the service contract the other 20 rollback tests pin.

Companion service changes (uncommitted salvage completed): inspect() refuses a
removed version reinstalled under different bytes; activation freezes
`installed_by` at first activation; resume re-evaluates compatibility against
the platform as it stands now.

Fail-before evidence: muting the new `InspectionConflict` raise makes
`test_reinstall_of_removed_version_with_different_bytes_is_refused` fail
(record silently created); reverting the `installed_by` freeze makes
`test_later_activations_preserve_the_original_installer` fail
(record re-attributed to `operator-9`). Both mutations were reverted before
commit.

Validation on this head: `pytest packages/maistro-core/tests/extensions
packages/maistro-server/tests/api/test_extensions_api.py
packages/maistro-server/tests/api/test_extensions_lifecycle_api.py` — 213
passed; `ruff check .` and `ruff format --check .` clean; mypy clean on the
extensions surface.
