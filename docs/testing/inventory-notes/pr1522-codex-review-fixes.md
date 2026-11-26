---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
  packages/maistro-core/tests: +7
  packages/maistro-server/tests: +3
---
# pr1522-codex-review-fixes

Fixes PR #1522's four Codex review findings (#1079 governed model egress).
Not a pure addition in `packages/maistro-core/tests`: it removes a duplicate
test class's suite and adds a replacement for the correct one, alongside new
coverage for each fix.

- **Finding 1 (P1, config threading)** -- `packages/maistro-server/tests`:
  new file `test_agent_config_model_bindings.py` (+3) proves a real
  `maistro.yaml` `model_bindings:` section reaches `AgentConfig.model_bindings`
  through the real `load_yaml_config()` loader and `_agent_config()`, and
  resolves through a real `create_container()` -- not a `SimpleNamespace`
  stand-in. `test_agent_config_security.py` gained a `model_bindings=[]` field
  on its existing fixture (no test count change). `packages/hive-conductor/backend/tests`:
  `test_maistro_core_adapter.py` (+2) proves the same threading through
  `_construct_runtime()`'s new `Settings.maistro_model_bindings` (JSON env
  var, same pattern as `MAISTRO_PERMISSIONS`).
- **Finding 2 (P2, credential cooldown reset)** -- `packages/maistro-core/tests`:
  `test_router.py` (+4) proves `CredentialRouter.add()`/`CredentialPool.upsert()`
  preserve `blocked`/`cooldown_until`/`error_count` across a re-register,
  update only the secret, and still start a genuinely new key id with clean
  health. `packages/hive-conductor/backend/tests`: `test_governed_model_consumers.py`
  (+1) proves `control_plane_binding()` no longer clears a 401-driven block
  across two consecutive calls reusing the same Workspace/Project.
- **Finding 3 (P2, duplicate/mismatched PgInvocationStore)** --
  `packages/maistro-core/tests`: `test_invocation_store.py` (-5) drops the
  fake-pool suite for the now-deleted duplicate `PgInvocationStore` in
  `maistro.capabilities.invocation_store` (its `payload_json`/`datetime`
  columns never matched migration 035's real DDL and nothing in production
  wired it). New file `test_pg_invocation_store.py` (+6) covers the store the
  container actually wires (`maistro.capabilities.pg_invocation_store.PgInvocationStore`)
  against a fake pool shaped like migration 035's schema (`payload` JSONB,
  `created_at` a float) -- one more case than before: the removed suite's
  single "create conflict" test conflated two distinct outcomes
  (`_find_effect` matching vs. not), split here into
  `..._active_effect_conflict_raises_unsafe_retry` and
  `..._id_collision_without_a_matching_effect_raises_value_error`.
- **Finding 4 (P2, unregistrable custom credential_refs)** --
  `packages/maistro-core/tests`: `test_model_binding_bootstrap.py` (+2)
  replaces `test_bootstrap_preserves_explicit_credential_refs` (which
  asserted the exact silently-broken behavior Codex flagged: a custom
  `credential_refs` value loads without any credential ever able to satisfy
  it) with `test_bootstrap_preserves_explicit_default_credential_ref` (same
  intent, using the one ref this bootstrap can actually register) plus two
  new fail-fast tests proving `bootstrap_model_bindings()` now raises
  `ConfigError` for a custom ref, with and without a gateway key configured.

