---
inventory-delta:
  packages/maistro-rsi/tests: +2
---
# repair-1096-seam-probe

## What moved

`packages/maistro-rsi/tests/test_autorun.py`, the guarded-sync-seam section
(ADR-102 AC-1). Net +2 node IDs: two tests rewritten, three added.

The prior verification round's executed seam probe reached a loopback server
with status 200 through `autorun._post`, because the helper called
`configure_outbound_policy(url)` on its own argument — caller input
authorized itself before the guarded transport could validate it (#1096).

The fix moves the allowance to where the settings object is read
(`make_llm_proposer._propose` registers `settings.litellm.base_url`, the
operator-configured gateway) and removes it from `_post`.

## Test changes

- **Removed** `test_post_registers_its_endpoint_and_sends_through_the_guarded_seam`
  — it asserted the bypass as a feature (`_post` registering its endpoint).
- **Added** `test_post_reaches_an_operator_configured_origin_through_the_guarded_seam`
  — a real loopback HTTP server (not `MockTransport`, whose fabricated
  responses never touch the guarded transport) reached through the seam once
  its origin is operator-configured.
- **Added** `test_post_never_authorizes_the_url_it_is_handed` — the exact
  regression probe: an unconfigured private origin raises
  `OutboundBlockedError` and leaves the policy unchanged.
- **Added** `test_proposer_registers_the_configured_gateway_origin` — the
  allowance the proposer needs comes from settings at the point settings is
  read.
- **Rewrote** `test_registration_is_exact_and_the_guard_stays_active_for_everything_else`
  to configure a distinct origin explicitly instead of relying on `_post`'s
  removed self-registration, and to pin the exact-origin comparison
  (`gw.test:4000` allowed, `gw.test:4001` not).

`scripts/check-security-inventory.py` gained a census for the defect class
itself (`_self_authorized_fetch_helpers`): a function that passes the same
name to `configure_outbound_policy` and to an outbound client call is
reported as a self-authorized fetch. It flags the pre-fix `_post` at the
line the probe cited and is clean on the fixed tree.
