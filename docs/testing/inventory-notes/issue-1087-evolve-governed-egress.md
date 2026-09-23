---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/hive-conductor/backend/tests: +0
---
# issue-1087-evolve-governed-egress

Issue #1087 keeps the shipped Evolve path on the canonical model egress.
The service adapter test exercises an operator-declared model Binding,
canonical model-chat execution, and Invocation correlation to Run, NodeRun,
and Attempt. The canonical graph contract tests verify that contextual model
calls receive the physical evaluation/finalization NodeRun identity and that
failed physical work cannot publish domain mutations (test-level deltas are
itemized in `auto-1087-6da5.md`; none are counted here because that note
already banks this issue's backend test additions against develop's merged
#1064/#1065 baseline).

After the develop merge, the maestro-core model-egress composition tests
(`test_model_egress_container_composition.py`) are develop's own superset —
including the disabled-Binding kill-switch and blank-scope validators — so
this issue carries no additional core test delta beyond it.

The direct-egress inventories remove `services.evolution`; the standalone
`maistro_evolve.providers.openai_compatible` adapter remains an intentionally
unreachable library boundary and is not used by production Evolve entry
points.
