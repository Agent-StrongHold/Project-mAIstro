---
inventory-delta:
  packages/maistro-core/tests: +3
  packages/hive-conductor/backend/tests: +4
---

# Tests for durable boot registration (#1759)

Seven additions, nothing removed or renamed.

## `packages/maistro-core/tests` (+3)

`capabilities/test_binding_invocation.py`, class
`TestBootRegistrationSurvivesRestart`. These cover `register_boot_binding`,
the seam a composition root calls on every start:

- `test_a_second_boot_reuses_the_stored_record` — a durable store compares the
  whole `Binding`, and two processes build theirs with different
  `created_at`, so a plain `put` succeeded on the first boot and raised
  `ValueError` on every one after. Also asserts `created_at` is *not*
  restamped: reusing the stored record keeps the real first-registration
  time, which is the only thing that field is for.
- `test_a_redefined_boot_binding_is_still_refused` — only `created_at` is
  forgiven. Without this, the reuse that fixes restarts would also silently
  accept an identity whose capability or scope had changed under it.
- `test_a_revocation_still_refuses_the_identity_on_a_later_boot` — reuse must
  not become a way to re-grant what an operator withdrew.

## `packages/hive-conductor/backend/tests` (+4)

`test_capabilities_wiring.py` (+3):

- `test_self_repair_registers_against_a_durable_binding_store` — asserts the
  Binding is in the **store**, not merely that the registry has a provider.
  The invoker resolves that identity on every repair, so registry-only would
  still fail at the first real call.
- `test_self_repair_survives_a_restart_against_the_same_database` — boots
  twice against one SQLite database and asserts self_repair registers both
  times. This is the one that fails against the first version of the fix.
- `test_a_revocation_that_outlived_a_restart_still_disables_self_repair` —
  the durable tombstone in `capability_binding_revocations` outlives the
  process, so boot must not re-grant across a restart. This is the property
  the removed `isinstance` gate was protecting, and it has to survive opening
  the seam.

It also **replaces** `test_self_repair_disabled_when_binding_store_lacks_boot_seam`
with `test_self_repair_disabled_when_the_boot_write_fails`: the old one pinned
the behaviour being removed, the new one keeps the fail-closed property that a
failed boot write registers *no* actor at all, rather than one holding an
identity the store has never heard of. Net +3 for the file.

`test_harness_routes.py` (+1):

- `test_the_route_registers_its_binding_in_a_durable_store` — the same
  property for `/v1/harness`, through the actual route, serving a session.
