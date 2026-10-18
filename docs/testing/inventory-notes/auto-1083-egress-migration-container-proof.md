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
After the develop sync that made the canonical execution spine mandatory
(#1113, `require_graph_execution_spine`), the unconfigured case boots the same
real Container and strips every gateway endpoint/credential source instead of
running containerless: a `None` container bridge is now refused before
admission (`CanonicalGraphUnavailable`), which the test also pins.

The companion runtime proof for the other migration entry
(`maistro.capabilities.providers.llm_gateway`) already exists in
`packages/maistro-core/tests/test_model_egress_container_composition.py`, so
that suite's count is unchanged. No existing tests were removed or renamed.

Closure evidence (candidate commit `9dacf9bc6`, repair round merged with
develop `35a72ff54`): exact local commands
`uv run pytest packages/hive-conductor/backend/tests/test_legacy_dag_node_container_composition.py -q`
(3 passed) and
`uv run pytest packages/maistro-core/tests/test_model_egress_container_composition.py -q`
(6 passed); CI execution legs are `.github/workflows/ci.yml` `python -m pytest
packages/hive-conductor/backend/tests -v --tb=short` (plus the cross-suite
leakage job `uv run pytest tests/ packages/hive-conductor/backend/tests
packages/maistro-design/tests -q --timeout=60`) and `.github/workflows/
quality.yml` `uv run coverage run --branch --source=packages/maistro-core/src/
maistro -m pytest packages/maistro-core/tests --timeout=30 -q` (the only
executor of that suite per the execution-partition test).
