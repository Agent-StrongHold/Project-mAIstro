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

## Third develop sync (e20e9f52, current develop tip): merge finished, delta +0

The preserved conflict state resolved here was a third `origin/develop` sync,
`git fetch origin develop` -> `e20e9f52` (unchanged from `MERGE_HEAD`). It was
a **criss-cross** merge: `git merge-base --all HEAD e20e9f52` returns two
unrelated bases (`420d503d4` from the previous sync and `94781cf6b`), so git's
recursive strategy merged the bases into a virtual ancestor and wrote
`<<<<<<< Temporary merge branch 1/2` markers **into that ancestor** — the
index stages carried markers that never existed on either tip. The marker text
in the conflicted worktree files was therefore not trustworthy as a record of
"ours" vs "theirs", and the resolution re-derived it per path instead:

    git diff 420d503d4 HEAD -- <path>   # empty for all 13 conflicted paths

The lane has **no own change** in any conflicted path (it is byte-identical to
the previous sync point, which is itself on develop's history), so each
resolution takes the develop tip blob verbatim:

`.github/workflows/quality.yml`, `.gitleaksignore`,
`deploy/scripts/verify-restore.sh`, `docs/install/deployment-topology.md`,
`packages/maistro-core/src/maistro/container.py`,
`packages/maistro-core/src/maistro/persistence/{pg_audit,sqlite_audit}.py`,
`packages/maistro-core/src/maistro/sandbox/backends/bubblewrap.py`,
`packages/maistro-core/src/maistro/security/sentinel/audit.py`,
`packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py`,
`pyproject.toml`, `tests/cross_product_parity/harness.py`,
`tests/security/test_sentinel_permission_table_armed.py`.

No test was added or removed by this round, so the front-matter delta stays
**+0**; `scripts/check-suite-inventory.py` reports 21/21 suites matching the
recorded baseline.

### Post-merge contribution of this lane

`git diff --stat e20e9f52 HEAD` after the merge lists **only this note**. The
M9-B3 lifecycle (pin / upgrade preflight / authority delta / explicit
reauthorization / rollback / disable / resume / remove) is develop's canonical
implementation — `maistro/extensions/service.py`,
`maistro/extensions/authority.py`, the store seam and the server routes in
`maistro_server/api/extensions.py` — and it is wired into production through
`Container.ensure_extension_install_service()` (the `get_extension_service`
dependency every lifecycle route uses). This lane's surviving contribution is
therefore the sync record and the evidence below, not new production code;
the epic's acceptance is proven against develop's implementation rather than
against a branch-local draft that the syncs superseded.

### Evidence recorded for this round

- merge resolution: no conflict markers anywhere (`scripts/check-merge-markers.py`
  ok); `quality/` is byte-identical to develop
  (`git diff --numstat e20e9f52 HEAD -- quality/` empty).
- acceptance, by node id, all passing:
  `TestUpgradeAuthority::test_same_authority_upgrade_changes_exactly_the_snapshot`,
  `TestUpgradeAuthority::test_broader_upgrade_parks_until_reauthorized`,
  `TestRollback` (broadened-authority refusal before any state change,
  incompatible target, wrong payload records nothing, retry idempotent),
  `TestDisableResume::test_disable_stops_new_use_immediately_and_keeps_evidence`,
  `TestRemove::test_remove_stops_use_and_preserves_historical_evidence` /
  `test_default_policy_is_retain_all` /
  `test_janitor_failure_aborts_removal_with_the_record_untouched` /
  `test_remove_twice_is_idempotent`,
  `TestConcurrentActivation::test_concurrent_installs_of_one_extension_leave_exactly_one_active`,
  plus restart durability
  (`test_install_store_conformance.py::test_restart_reads_the_same_records_with_the_same_evidence`)
  and `scripts/extension_lifecycle_proof.py` (PROVED 10/10 stages, 42/42 checks).
- suites: `packages/maistro-core/tests` 15646 passed / 1131 skipped / 7 xfailed;
  `packages/maistro-server/tests` 571 passed / 8 skipped; extensions subset
  1115 passed.
- gates: `ruff check .`, `ruff format --check .`, mypy over CI's ten package
  sources (1066 files, no issues), `check-vulture-baseline.py`
  (1326 identities), `check-suite-inventory.py`, `check-shipped-surface-truth.py`,
  `check-backlog-consistency.py`, `check-execution-lifecycles.py`,
  `check-api-route-contracts.py`, `check-extension-imports.py`,
  `check-cross-package-imports.py`, `check-dependency-namespaces.py` — all ok.

### Residual risk

- This round changes no production code, so it cannot regress behavior — but
  it also adds no new acceptance test of its own: the lifecycle acceptance
  rests entirely on develop's suites, which this lane now inherits unchanged.
- `test_post_install_lifecycle.py::TestDisableResume` proves "new use stops
  immediately" at the resolution seam (`ExtensionInstallService.active()` and
  `installed_versions()`, both consulted by the operational views). There is no
  dispatch-level check to bypass today: `ExtensionHost` — the only seam that
  runs extension code — is not yet wired into a production invocation loop
  (`grep -rn 'ExtensionHost\(' packages/*/src` only finds the ext-harness's own
  unrelated class in `maistro_ext_harness`; the canonical
  `maistro.extensions.host.ExtensionHost` has no construction site outside
  `__init__` re-export and the vulture whitelist), so the pointer is the whole
  of the enforcement. Wiring the host into a run loop later must keep
  resolving through `ExtensionInstallService.active()`, or a disabled record
  would stay invocable.
