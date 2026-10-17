---
inventory-delta:
  packages/maistro-core/tests: +4
---
# chatgpt-m1-1079-egress-composition-v2-a319

4 new tests in `packages/maistro-core/tests/capabilities/test_llm_gateway_branches.py`
covering the #1079 finding-5 fix: `_checked_body()`'s 401/429/4xx errors now
carry `status_code` (via new `LlmAuthError`/`LlmHttpError` subclasses) so
`CredentialRouter` can actually classify and block/cool the credential,
instead of falling through to `ErrorCategory.UNKNOWN`.

- `test_checked_body_401_carries_status_code_for_credential_routing`
- `test_checked_body_429_carries_status_code_for_credential_routing`
- `test_checked_body_other_4xx_carries_status_code_for_credential_routing`
- `test_credential_router_blocks_and_cools_on_the_carried_status` — an
  end-to-end proof through `CredentialRouter`'s own status extraction and
  cooldown table, not just that the exception carries the attribute.

No net-new tests in `test_sync_kinds_branch_coverage.py` — its 3 affected
assertions were updated in place to the new, more specific exception class
names (`LlmAuthError`/`LlmHttpError`), and its `llm_binding_id` fixture now
resets credential cooldown/blocked state per test to isolate it from the
shared `default_effect_context()` process-wide singleton.
