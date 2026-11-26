---
inventory-delta:
  tests/: 0
---

# auto-1095-review-renumber-068

Addressing the P1 review finding on the legacy-principal ownership revision:
the migration had claimed id `064`, but develop's parent history already
shipped `064_canonical_personas`, `065_event_replay_cursors`,
`066_durable_delivery_receipts` and `067_delegation_grants`. Alembic matches
databases by revision id only, so an installation stamped at develop's `066`
would be treated as past three revisions it never ran and would upgrade
straight past the ownership migration — stranding every installer-era
`default` ownership row after the installer key becomes `conductor`. The live
suite missed it because its fixture started from `063` instead of develop's
landed tip. No test counts move.

## Resolution: keep develop's landed identities; ownership migration appends as 068

Per the recorded integration rule (`063_canonical_goals`, the #1572
clarification, and the convention develop itself applied in `9854033c7`):
merged identities keep their meaning, a landed trunk migration never moves,
and a new revision appends after the integrated head under an unused id.

- The four renumbered variants are replaced by develop's files byte for byte:
  `064_canonical_personas.py`, `065_event_replay_cursors.py`,
  `066_durable_delivery_receipts.py`, `067_delegation_grants.py`.
- `alembic/versions/068_legacy_principal_ownership.py`: `revision = "068"`,
  `down_revision = "067"`; body unchanged from the reviewed `064` (the
  audit-log signature probe from `078304cb1` included).
- Chain pins updated: `test_capability_invocation_effect_index_migration.py`
  (head/lineage narrative), `test_goal_installed_base_upgrade.py`
  (`CHAIN_HEAD = "068"`, lineage and filename assertions),
  `test_legacy_principal_ownership_live.py` (fixture now upgrades to `067` —
  the stamp a real upgraded deployment carries — before walking to `068`),
  `test_durable_delivery_receipts_downgrade.py` (`066`),
  `test_event_schema_agreement.py` (`064:065`, `065:066`),
  `test_legacy_principal_migration.py` (path/revision),
  `test_migration_chain.py` prose.
- Prose pins: `quality/durable-table-retention.json` (owner module + notes),
  `pg_stores.ensure_event_schema` docstring (004/036/065/066, mirror 066),
  `retention_scope.py` (delegation grants at alembic 067 — already correct
  under the restored identities), `test_container_wiring.py` (replay cursors
  at 065).
