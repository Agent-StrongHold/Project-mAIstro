---
inventory-delta:
  packages/maistro-core/tests: 2
---

# #1084 Agent model callers

Parametrize the existing real governed Agent completion/usage test over a canonical
matching turn id, a distinct domain turn id, and no turn id (+2 cases). The Hive
bridge test now verifies that later materialization receives GovernedLLMClient
over the same Container collaborators; its collected count is unchanged.
