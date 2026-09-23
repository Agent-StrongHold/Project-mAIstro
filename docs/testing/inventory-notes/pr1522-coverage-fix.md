---
inventory-delta:
  packages/maistro-core/tests: +22
---
# pr1522-coverage-fix

Closes the diff-coverage CI failure on PR #1522 (Binding-scoped credential
routing for governed model egress, #1079/#1091) by adding tests for code the
PR newly introduced or touched; nothing moved or was removed.

+22 net new node IDs in `packages/maistro-core/tests`, all additions:

- `tests/capabilities/test_binding_invocation.py` (+13): `SqliteBindingStore`
  and `PgBindingStore` had no direct tests at all (only `InMemoryBindingStore`
  was covered) -- added put/get/resolve coverage for both, including the
  immutable-redefinition refusal and the `PgBindingStore` "insert executed but
  the row still isn't there" defensive `RuntimeError`. Also added one direct
  unit test of the private `_scope_checked` helper's own required-field guard
  (unreachable through any store's public `resolve()`, which validates first).
- `tests/capabilities/test_invocation_store.py` (+6): `PgInvocationStore` in
  this module (distinct from the one the container actually wires from
  `maistro.capabilities.pg_invocation_store`, per its own docstring) had zero
  tests. Added create/get/save/list_effect coverage, including the
  already-exists and does-not-exist refusal paths, against a fake
  asyncpg-shaped pool.
- `tests/capabilities/test_model_binding_bootstrap.py` (new file, +7):
  `bootstrap_model_bindings` had no tests. Covers both partial branch arcs CI
  flagged -- whether a declared Binding's `credential_refs` get defaulted to
  the gateway's default credential id, and whether a reload preserves an
  already-registered Binding's `created_at` -- plus the surrounding
  happy-path/fail-closed behavior.
- `tests/capabilities/test_model_chat_egress.py` (+2): added the two refusal
  paths inside `ModelChatEgress.complete()`'s physical `execute()` closure
  (non-`CredentialBackedProvider` and credential-backed-but-non-gateway
  provider) that credential routing normally prevents from being reached on
  the governed path -- defense-in-depth checks exercised the same way the
  file's existing `test_usage_from_without_tracked_provider_returns_none`
  reaches the raw resolver/executor, by stubbing `effects.invocations.invoke`
  to capture them.
