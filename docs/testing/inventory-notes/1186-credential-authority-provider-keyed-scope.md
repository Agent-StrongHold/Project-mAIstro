---
inventory-delta:
  tests/: +5
---

# Issue #1186 repair: provider-keyed scope trigger for the credential authority gate

Verify finding (job 37aa0b11, NEEDS-REPAIR): `scripts/check-credential-authority.py`
only invoked owner-scope checking for id/record selectors or list operations, so
injected unscoped `set_secret(provider, secret)` / `delete_secret(provider)`
global-bucket fixtures inside an approved surface returned no failure from
`_owner_scope_failures`. The acceptance criterion "fail if an unscoped credential
implementation becomes production reachable" was therefore not met for
provider-keyed operations.

Gate repair (same commit, no inventory impact): `_owner_scope_failures` now
requires sink evidence for any operation whose parameters can address or carry a
credential record — id/record selectors, the canonical (provider, workspace,
connection) scope selectors, and secret-bearing values — not only id/record
selectors and lists. Bare `key` parameters remain outside per-user scope because
master-key material administration (`rotate_master_key`) is deployment-scoped,
matching the documented policy that key-material administration is not per-user
record CRUD.

Test additions (5 node IDs in `tests/test_credential_authority.py`):

- Three new parametrize cases (`provider-set`, `provider-delete`, `provider-get`)
  in `test_unscoped_operations_inside_an_approved_module_fail` reproducing the
  executed verify fixtures: unscoped provider-keyed global-bucket
  set/delete/read must now fail with "lacks owner/principal scope at a canonical
  storage sink".
- `test_provider_keyed_operations_with_owner_scope_pass`: the canonical
  provider-keyed shapes with a required `user_id` reaching
  `self._load()` buckets (`setdefault`/`get`) produce no failure, pinning that
  the strengthened trigger does not false-positive on the real store.
- `test_key_material_administration_is_not_per_user_record_crud`:
  `rotate_master_key(new_key)`-shaped key-material administration stays outside
  the per-user scope lint, pinning the bare-`key` exclusion.

Result: `uv run pytest tests/test_credential_authority.py -q` => 57 passed;
`RATCHET_BASE_REV=ffd6fdb16da57abd0a51198016e44b878be470d5 uv run python
scripts/check-credential-authority.py` => OK on the committed policy.
