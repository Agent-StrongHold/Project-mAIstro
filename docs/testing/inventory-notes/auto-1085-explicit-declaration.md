# Auto-1085 repair 3: explicit-declaration-only default model binding


Third repair round for #1085 (authorization-truthfulness findings). No net
change to collected node count; three tests changed meaning:

- `test_maistro_core_adapter.py`:
  `test_start_can_disable_the_default_model_binding` is renamed to
  `test_start_without_a_binding_declaration_provisions_nothing`. The old test
  passed `maistro_model_binding_id=""` explicitly, which could not catch the
  shipped default being non-empty. The new test starts the real bridge with
  default Settings (asserting the shipped default is empty), proves NO
  binding is minted, and drives a stored DAG model node through the real
  facade + canonical durable Run path to a fail-closed refusal with zero
  Invocations.
- `test_maistro_core_adapter.py`:
  `test_start_provisions_the_declared_default_model_binding` now declares the
  binding through `MAISTRO_MODEL_BINDING_ID` -- the production declaration
  point both the bridge Settings and the node-side fallback read -- instead of
  relying on the (removed) non-empty Settings default.
- `test_canonical_dag_runner.py`:
  `test_hive_facade_uses_governed_model_egress_on_canonical_run` registers
  `ModelMetadata` for the pinned model and asserts the Invocation's usage
  evidence carries provider and computed `cost_cents` (closes the
  "cost-specific evidence UNVERIFIED" gap).
- `test_canonical_dag_runner.py`:
  `test_hive_gateway_failure_terminalizes_canonical_run_and_node` now asserts
  the owning Attempt's truthfulness: terminal `COMPLETED`-as-physical-try
  (ADR-081226-69ee; same semantics core pins in
  `test_node_retry_attempts.py`), correlated to the failed Invocation, with
  its persisted NodeResult evidence reporting `success=False`/`failed`. This
  documents the reconciliation of the issue's "Attempt fails truthfully"
  wording with the accepted ADR execution model.
