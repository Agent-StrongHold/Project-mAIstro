---
inventory-delta:
  packages/hive-conductor/backend/tests: +25
---
# 1087-evolve-model-correlation

This bounded #1087 salvage removes six old service-test cases and adds two
parameterized no-authority refusal cases plus 29 real-composition cases (+25).
The old cases asserted raw HTTP/stub fallback, swallowed builder failures, or
synthetic cycle/Attempt correlation. Their replacements assert fail-closed
behavior with or without a configured gateway URL and prove real persisted
execution identity through the production adapter. Malformed-response coverage
moves into the real-composition suite and now also verifies failed Run/score
publication, rather than checking only a fake egress closure's exception.

The new tests compose the real graph executor, production proxy IFEval runner,
population/archive, declared Binding bootstrap, scoped credential router,
model Egress, Invocation store and quota recorder; gateway HTTP and corpus size
are controlled. Existing domain-only route doubles explicitly inject a non-model
callable, preserving their execution/domain scope without implying raw fallback.

Evidence covers actual Run/NodeRun/Attempt/actor correlation, accepted domain
scores and archived provenance, scope/Binding/policy/credential refusal,
request defaults and overrides, replay across real reclaimed Attempts without double quota, UNKNOWN-effect
refusal, a real SQLite quota-budget denial, request-route dispatch, expired context,
malformed responses, swallowed/cancelled model errors, and finalize's existing
committed/faulted reconciliation markers. No population/tournament/recovery
owner is replaced.

This does not resolve #1867. Unattended cadence still has no selected admitted
actor; no service actor, cadence policy or readiness behavior is introduced.
