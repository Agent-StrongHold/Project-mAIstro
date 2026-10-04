---
inventory-delta:
  packages/maistro-core/tests: +3
  packages/maistro-server/tests: +0
---
# auto-42 CI radon repair

`test_effect_claim_refuses_an_unanchored_parent_node_reference` exercises the
shared effect-claim parent validator through every canonical RunStore backend.
It proves an effect-keyed child Run cannot be persisted with a NodeRun parent
reference that lacks its parent Run correlation. The recorded `+3` matches the
current collected delta; the other two nodes are already-present branch
additions not represented in their earlier inventory notes.
