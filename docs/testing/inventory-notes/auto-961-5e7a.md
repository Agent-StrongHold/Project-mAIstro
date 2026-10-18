---
inventory-delta:
  packages/maistro-core/tests: +13
---

# auto-961-5e7a

Follow-up tests for the #961 provider adapter SDK after the 961-provider-adapter-sdk
note (+53). Twelve live in `packages/maistro-core/tests/capabilities/test_provider_adapters.py`
and one in `test_governed_llm_execution_identity.py`; collected count for the suite
on this tree is 13834 (13821 + 13).

- **`test_unpinned_routing_falls_through_unhealthy_adapter`** (commit 1965ec623)
  pins the review-fix behavior: adapter health is synced into canonical registry
  availability at `note_health` time, so `CostAwareRouter` skips an unhealthy
  adapter's models up front and the ADR-038 fallback chain reaches a healthy
  candidate instead of one failed adapter taking all unpinned traffic offline.
  A recovery probe re-marks the models available.

- **`test_unpinned_adapter_binding_stays_within_its_declared_adapter`** — an
  unpinned Binding whose `config` records `adapter_id` must never route to a
  faster model outside its own adapter: its `credential_refs` authorize only
  that adapter's reference, so a wider pick would resolve fine and then fail at
  credential acquisition. Selection passes a `scope` to `CostAwareRouter.select`
  constrained to the adapter's declared models; an adapter with no eligible
  models is `Unavailable`, never a silent re-scope to models another adapter
  could serve.

- **`test_nested_catalog_close_restores_outer`** — the process-default catalog
  is a stack, not a single slot: closing an inner container hands the default
  back to the still-open outer one instead of dropping the process to
  "no adapters" (same out-of-order-close rule as the effect-context stack,
  #1362).

- **`test_republish_moves_catalog_to_top_without_duplicate`** — re-publishing a
  catalog already on the stack moves it to the top rather than recording it
  twice, so a later release cannot leave a stale duplicate behind it.

- **`test_bootstrap_restarts_idempotently_against_a_durable_binding_store`** —
  a second `bootstrap_provider_adapters` over a durable (SQLite) Binding store
  preserves the stored `created_at`, so the store's immutability check sees an
  identical definition instead of rejecting the re-registration as a changed
  one (same seam as `bootstrap_model_bindings`).

- **`test_stream_contract_yields_exactly_one_canonical_body`** (in
  `test_governed_llm_execution_identity.py`) — pins the streaming half of the
  #961 acceptance: the canonical stream contract is one governed completion,
  never a raw provider stream fan-out. `ModelChatRequest` carries no stream
  field, so no provider — adapter-backed or gateway — can stream raw through
  the governed seam.

- **`test_adapter_config_refuses_blank_identity_or_scope_fields`** (3 cases),
  **`test_adapter_config_refuses_a_blank_credential_reference`** (2 cases) —
  the `AdapterInstanceConfig` validators refuse blank adapter/binding/project
  identity and whitespace credential references, so a misconfigured adapter
  entry fails at wiring, not at first egress.

- **`test_container_close_withdraws_its_published_adapter_catalog`** and
  **`test_container_close_without_a_catalog_leaves_the_default_alone`** — both
  arcs of the close-time guard: `create_container` always publishes its
  (possibly empty) adapter catalog as the process default and `aclose()`
  withdraws exactly it, while a container holding no catalog withdraws
  nothing.

## Ledger repair carried in this round

Two vulture identities the health-sync fix made live were pruned from
`quality/vulture-baseline.json` (`InMemoryProviderRegistry.mark_available` /
`mark_unavailable`): fixed debt must leave the ledger.
