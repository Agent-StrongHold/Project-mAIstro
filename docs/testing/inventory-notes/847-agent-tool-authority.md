---
inventory-delta:
  packages/maistro-core/tests: +9
---

# Issue 847 tool authority coverage

Adds focused coverage for model-selected missing schemas, identity/host tool-set
intersection, write-scope narrowing, the Agent's strategy callback wrapper, and
typed schema denial. BuildersLearningStrategy no longer performs repository,
GitHub, or command effects through an arbitrary callback; those effects remain
owned by governed Builders graph nodes. Sandbox and HTTP command tests also
cover shell-operator rejection and structured argv execution, plus Git ref/repository
option-injection rejection.
