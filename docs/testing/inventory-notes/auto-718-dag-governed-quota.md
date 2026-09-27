---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# auto-718-dag-governed-quota

Three tests in `packages/hive-conductor/backend/tests/test_legacy_dag_governed_quota.py`,
new for issue #718. They pin the Workspace-DAG cutover: a legacy DAG LLM node
executed through `canonical_dag_runner.execute_dag` with a live Container now
crosses the governed Binding -> Invocation egress, so its usage lands on the
canonical quota ledger with provider/Invocation identity (`test_dag_node_model_call_records_invocation_quota_evidence`);
a gateway that omits usage records explicit unreported evidence instead of a
measured zero (`test_dag_node_without_provider_usage_records_unreported_evidence`);
and with no canonical effect authority the injected compatibility builder runs
while recording nothing (`test_dag_node_without_effect_authority_falls_back_and_records_nothing`).
No existing tests were removed or renamed.
