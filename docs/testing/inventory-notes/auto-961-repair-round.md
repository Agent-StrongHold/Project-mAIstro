---
inventory-delta:
  packages/maistro-core/tests: +19
---

# Repair-round additions for the provider adapter SDK (#961)

Suite: `packages/maistro-core/tests` (node count recorded by
`scripts/check-suite-inventory.py`). This note covers the second repair round
on top of `auto-961-5e7a.md`; the develop sync that preceded it raised the
shared suite baseline, and this note adds the 19 nodes below on top of that
merged tree.

## Added (19 nodes, all in `capabilities/test_provider_adapters.py`)

- `test_spec_refuses_malformed_or_userinfo_base_urls` (5 parametrized cases) —
  `base_url` is validated by real parse: no host, non-absolute, unparseable
  IPv6, and userinfo-carrying URLs all refuse at spec validation.
- `test_registration_refuses_a_non_json_serializable_payload` — conformance
  serializes with the transport's strict encoder (no `default=str`), so a
  `Decimal` in a later model's payload fails registration, not the first HTTP
  call; nothing is recorded on refusal.
- `test_registration_refuses_an_adapter_failing_on_a_later_model` — request
  conformance exercises *every* declared model, not only `models[0]`.
- `test_conformance_refuses_a_taxonomy_contradicting_canonical_classification`
  — an adapter mapping HTTP 500 to `PERMANENT` fails registration: the
  taxonomy is pinned to what the canonical resilience classifier infers from
  the status.
- `test_reference_error_taxonomy_matches_canonical_classification` — the
  reference adapter agrees with every pinned status (408/409 now permanent,
  matching the classifier's non-transient set).
- `test_reference_payload_omits_an_unset_temperature` — `temperature=None`
  leaves sampling to the provider (merge reconciliation with the optional
  `ModelChatRequest.temperature`).
- `test_reference_model_declares_the_adapters_tools_and_structured_output` —
  the reference model restates the adapter-level capability flags, so a tools
  request against `reference-chat` resolves instead of refusing.
- `test_bootstrap_registers_the_reference_adapter_at_the_deployment_url` —
  bootstrap self-registers the reference adapter at `AgentConfig.litellm_url`,
  not the hardcoded Compose hostname.
- `test_boot_probe_covers_only_the_configured_adapter` —
  `probe_health_at_boot` on one entry probes that adapter only; a second
  registered adapter with a health path is never probed.
- `test_probe_adapter_for_an_unknown_id_reads_healthy` — unknown ids change
  nothing and read healthy (absence of signal stays optimistic).
- `test_bootstrap_scopes_the_binding_to_the_declared_node_and_policies` —
  `node_id`/`policy_refs` on `AdapterInstanceConfig` flow onto the loaded
  Binding, mirroring `ModelBindingConfig`.
- `test_adapter_config_refuses_a_blank_policy_reference` — blank refs in
  `policy_refs` refuse at validation.
- `test_bootstrap_allows_the_configured_adapter_origin` — the operator-named
  endpoint origin joins the outbound policy (private adapter endpoints are no
  longer SSRF-refused while the equally private `litellm_url` passes).
- `test_pre_effect_normalization_refusal_records_not_applied` — an adapter
  refusing a runtime input during request normalization raises
  `EffectNotApplied` (nothing crossed the transport), never an UNKNOWN
  Invocation.
- `test_create_container_accepts_a_host_registered_adapter_catalog` — the
  production composition root accepts a host-registered catalog through the
  new `provider_adapter_catalog` parameter; a configured out-of-tree entry
  resolves instead of failing with an empty-catalog `ConfigError`.

## Modified (behavior updates, node count unchanged)

- `AcmeAdapter.error_kind_for` and the reference adapter's now follow the
  pinned taxonomy (408/409 → permanent).
- Probe-based tests use `catalog.probe_adapter(<id>)` / `is_healthy` instead
  of the removed `probe_all`/`unhealthy_adapters`.
- The secret-free-payload test expects one conformance probe per declared
  model.
- The blank-credential-ref test matches the widened validator message
  (`credential_refs` and `policy_refs` share one refusal text).
