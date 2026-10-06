---
inventory-delta:
  packages/maistro-design/tests: +32
---
# 968 — Workspace-scoped pack lifecycle (M9-F3)

Adds the governed pack lifecycle (`packages/maistro-design/src/maistro_design/
packs/lifecycle.py` + `service.py`) over the #793 pack registry: per-Workspace
activation (`enable`/`disable`), configuration overrides, upgrade with
dependency/authority preflight, removal with owned-asset cleanup, and
snapshot-anchored new-use gates — with audited, atomic transitions behind a
`PackLifecycleStore` protocol (in-memory reference; a durable backend arrives
behind the same protocol, as the M9-B2 extension activation store did).

Enabling contract change: `DomainPack` and the three shipped manifests gain a
required `version` (release triple) — the identity Workspace activations are
recorded against — and `GoalRubricCatalog` gains `pack_version` provenance so
an instantiated catalog records which release its dimension defaults came
from. Template metadata carries `pack_version` too.

## packages/maistro-design/tests (+28)

- `test_pack_lifecycle.py` (32 cases), one class per issue acceptance
  criterion. The load-bearing ones:
  - `test_an_unupgraded_workspace_keeps_running_its_snapshot` — with the
    registry moved to a newer release, an unupgraded Workspace still
    materializes its activated release (byte-identical template content
    hash), proving an upgrade cannot silently rewrite what a Workspace runs.
  - `test_upgrade_blocked_until_the_new_backend_is_authorized` — a target
    release adding a backend is blocked in preflight until the Workspace
    grant lands, then upgrades.
  - `test_same_version_under_different_content_is_an_identity_conflict` —
    registry content drift under an unchanged version is refused, never
    reconciled against a Workspace snapshot.
  - `test_remove_tombstones_cleans_owned_assets_keeps_evidence` — removal
    runs the owned-asset cleanup before persisting, tombstones (never
    deletes) the record with its manifest snapshot retained, and leaves
    already-instantiated template/catalog values untouched.
  - `test_every_operation_commits_one_record_and_one_transition` — the store's
    single `commit` seam is the atomicity/durability point; a restarted
    service over the same store sees all state (the service holds none).
  - `test_stale_write_loses_the_compare_and_set` — `commit` is also the
    concurrency seam: a disable that read `ENABLED` and then raced a removal
    loses the compare-and-set, raises `PackConcurrentWriteConflict`, and the
    terminal `REMOVED` tombstone survives with no stale transition appended.
  - `test_stored_settings_cannot_be_mutated_through_shared_references` —
    `WorkspacePackConfiguration.frozen=True` is shallow, so the store
    deep-copies records on both the write and read seams; mutating `settings`
    through any handed-out reference edits a copy and appends no transition.
  - `test_upgrade_preflight_refuses_a_tombstoned_activation` — preflight
    treats a `REMOVED` tombstone like a missing record ("no active
    activation"), so it never advertises an upgrade `upgrade_pack` would
    refuse; `test_override_rejects_empty_selection` rejects an empty
    `rubric_dimension_ids` at the configuration model itself.
- `test_packs.py` — no count change; the three hand-rolled contract-edge pack
  dicts gain `"version": "1.0.0"` so they keep failing on the defect each
  test names rather than on the new required field.

Two mutation spot-checks were run and reverted: removing the enable-time
authority check fails `test_enable_requires_every_declared_backend`;
materializing from the registry instead of the snapshot fails both
`TestUpgradePreservesHistoricalRevisions` snapshot tests. Four more, over the
concurrency-salvage tests, run and reverted the same way: neutralizing the
store's compare-and-set fails `test_stale_write_loses_the_compare_and_set`;
dropping the read-seam deep copy fails
`test_stored_settings_cannot_be_mutated_through_shared_references`;
letting preflight ignore the `REMOVED` tombstone fails
`test_upgrade_preflight_refuses_a_tombstoned_activation`; deleting the
empty-selection validator fails `test_override_rejects_empty_selection`.
