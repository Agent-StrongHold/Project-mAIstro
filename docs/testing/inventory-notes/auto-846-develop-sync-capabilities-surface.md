---
inventory-delta:
  packages/maistro-core/tests: +0
---
# auto-846-develop-sync-capabilities-surface

Repair round for #846 (M2-A: remove default-allow and captured-provider
bypasses). The branch had a preserved, unresolved develop sync: the merge of
`origin/develop` (8bfd35903) stopped on two conflicts in the capabilities
package surface. Resolved in merge commit `2f05212e3`:

- `capabilities/__init__.py`: kept #846's removal of `AllowAllGate` from the
  public surface (the class no longer exists; `DenyAllGate` is the only
  shipped gate besides `ActionGate`) and kept develop's `ApprovalAuthority`
  export backed by the new `capabilities/authority.py` module.
- `capabilities/effect_context.py`: kept the public `binding_scope_policy`
  rename plus the explicit-installation-only contract from #846, and kept
  develop's legacy-tool effect floor (`REQUIRE_APPROVAL` for
  `legacy_tool:*` bindings marked `mutate`/`destroy`) in the function body.
  The docstring now documents both halves.

## Semantic reconciliation

develop's #1094 expected `new_effect_context()` to install
`binding_scope_policy` implicitly. #846 deliberately changed that default:
an omitted policy evaluator is an *unavailable dependency*, so the unnamed
context composes `_unconfigured_policy` and denies (`rule=invocation.unconfigured`)
instead of silently authorizing. The #846 fail-closed contract governs; the
#1094 legacy-tool floor is preserved through the explicit composition root
(`default_effect_context()` selects `binding_scope_policy` by name).

## Tests updated

- `packages/maistro-core/tests/capabilities/test_effect_context_policy.py`
  (3 tests, composition updated, no net count change): the legacy
  mutate/destroy REQUIRE_APPROVAL and read-passthrough cases now construct
  `new_effect_context(policy_evaluator=binding_scope_policy)` — the exact
  composition `default_effect_context()` performs — instead of relying on the
  removed implicit install. Module docstring now names `binding_scope_policy`
  (it still referenced the pre-rename `_m1_binding_authorized_policy`).

The fail-closed default itself remains covered by
`test_binding_invocation.py` (`InvocationDenied`, rule
`invocation.unconfigured`) and `test_governed_invocation.py` (policy-outage
deny with resolver/executor never invoked).

## Validation (merged tree @ 2f05212e3)

- `uv run pytest packages/maistro-core/tests/capabilities -q` → 349 passed.
- `uv run pytest packages/hive-conductor/backend/tests/test_harness_routes.py
  test_self_repair_routes.py test_capabilities_wiring.py -q` → 31 passed,
  including disable/revoke-after-initialization denial with
  `harness.sent == []` / `started == []` / `streamed == 0` (no provider call)
  and the shipped-route no-policy fail-closed case.
- `uv run python scripts/check_direct_effects.py` → exit 0; 45 sites, all
  dispositioned (CANONICAL_INVOCATION=2, MODEL_EFFECT=37, TOOL_EFFECT=6).
- `uv run ruff check packages/maistro-core packages/hive-conductor` → pass;
  `ruff format --check` on the touched files → pass.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0 (ratchet holds:
  1403 reviewed identities, 1402 findings against base 8bfd35903).
