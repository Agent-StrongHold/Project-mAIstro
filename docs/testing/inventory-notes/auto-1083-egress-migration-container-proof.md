---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# auto-1083-egress-migration-container-proof

Three tests in
`packages/hive-conductor/backend/tests/test_legacy_dag_node_container_composition.py`,
new for issue #1083: the `services.legacy_dag_node` entry in
`scripts/check-model-egress.py` `CANDIDATE_MIGRATIONS` (predecessor
`services.graph_runner`) previously had only the migration-map fixture
assertions in `tests/test_check_model_egress.py`, which prove which move was
approved but not that the moved call can execute. The new module is the
runtime half: a legacy DAG LLM node driven through the shipped
`canonical_dag_runner.execute_dag` composition over a real
`maistro.container.create_container` Container, with only the final physical
provider transport faked — proving the governed call reaches the pinned
provider and records canonical Invocation/Run/Attempt correlation
(`test_legacy_llm_node_reaches_the_pinned_provider_and_records_canonical_correlation`),
that an unconfigured gateway fails closed with no fabricated success
(`test_unconfigured_gateway_fails_the_legacy_node_closed_without_fabricated_success`),
and that removing the model-metadata registration the Binding pin depends on
fails the real container path closed
(`test_unregistered_model_metadata_fails_the_real_container_path_closed`).
The companion runtime proof for the other migration entry
(`maistro.capabilities.providers.llm_gateway`) already exists in
`packages/maistro-core/tests/test_model_egress_container_composition.py`, so
that suite's count is unchanged. No existing tests were removed or renamed.
