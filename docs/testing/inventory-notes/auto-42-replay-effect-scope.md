---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-42 replay effect scope

The harness replay test now uses two chronological NodeRuns and verifies that a
completed governed dispatch is reused through its stable logical effect scope,
while the persisted Invocation retains the first physical NodeRun and Attempt.
The durable executor contract test also verifies that an EFFECT_KEY declaration
without a runtime logical key fails closed instead of retrying an ambiguous
external effect.
