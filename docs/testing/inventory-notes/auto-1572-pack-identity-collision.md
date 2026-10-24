---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-1572-pack-identity-collision

One node ID, added on this branch at head `882fd6be6` together with the
fail-closed guard it pins in
`packages/maistro-core/src/maistro/extensions/packs.py`:
`InstallablePackRegistry.install` now refuses a pack whose `pack_id` is
already occupied by an active extension installed through the M9-B2 service,
raising `PackIdentityConflict` before compatibility evaluation. Without the
guard a later install would let `_active_versions` silently overwrite the
extension's resolved version, misdirecting dependency resolution to the wrong
provider while both objects answer to one identity.

`test_pack_id_colliding_with_an_active_extension_is_refused`
(`packages/maistro-core/tests/extensions/test_pack_contracts.py`) holds the
boundary from both sides: the install raises with the "already active as an
extension" message, and `records()` is still empty afterwards — the refusal
happens before any record is created, so a partially installed shadow cannot
survive the failed call. It is a plain unit test over the in-memory registry;
no parametrization, no skip conditions, hence exactly +1 collected node ID in
the `packages/maistro-core/tests` suite. No other suite moved: the merge of
develop base `0d49d4e06` into this branch carried no test-count change
relative to the recorded baseline-plus-deltas, which the full-tree collection
for this update re-confirmed (17 suites, 30809 collected, zero duplicate
evidence).
