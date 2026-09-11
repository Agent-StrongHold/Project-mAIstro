---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/maistro-core/tests: +3
---
# issue-1087-evolve-governed-egress

Issue #1087 keeps the shipped Evolve path on the canonical model egress.
The service adapter test now exercises an operator-declared model Binding,
canonical model-chat execution, and Invocation correlation to Run, NodeRun,
and Attempt. The canonical graph contract test also verifies that contextual
model calls receive the physical evaluation/finalization NodeRun identity.

The direct-egress inventories remove `services.evolution`; the standalone
`maistro_evolve.providers.openai_compatible` adapter remains an intentionally
unreachable library boundary and is not used by production Evolve entry
points.
