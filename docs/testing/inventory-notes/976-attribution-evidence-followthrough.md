---
inventory-delta:
  packages/maistro-core/tests: +1
---
# #976 AC-2 follow-through: programmatic-adapter attribution evidence

Lane `auto-976` repair follow-ups to the issue-implementation round moved
`packages/maistro-core/tests` by one net node:

- `a31ca4a49` "attribute programmatically registered declaring adapters in
  invocation evidence" adds `test_programmatic_registration_leaves_full_attribution_evidence`
  (`@pytest.mark.ac("#976/AC-2")`): a fully declaring adapter registered onto an
  existing `Binding` via `register_adapter_models()` → `complete()` — the
  non-bootstrapped path that never runs the bootstrap copying identity into
  `Binding.config` — still carries extension identity through the Invocation
  snapshot *and* the terminal `capability.invocation.completed` audit event's
  `provenance["extension"]`. One non-parametrized async case = +1 node.
- `1381d31be` "render attribution log fields into the configured log output"
  adds rendering assertions to existing cases (the configured-log-output
  repair) — no new collection node.

No test was removed or renamed; the net for the suite is +1, matching the
recorded delta. The case asserts the canonical correlation fields stay
authoritative (`correlation_id == run_id`) while the extension identity rides
only under `provenance["extension"]`, the same seam the implement-round note
documents for the bootstrapped path — here proving it for the programmatic
registration path too.
