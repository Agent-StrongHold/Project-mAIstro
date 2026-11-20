---
inventory-delta:
  packages/maistro-core/tests: +2
---
# Issue #57: recover durable prediction-mismatch evidence

Two parametrized cases use the real SQLite Binding/Invocation/Event stores and
close/reopen the database with fresh canonical effect contexts. Injecting a
mismatch-event append failure before commit or after commit (lost acknowledgement)
must not prevent a later replay from retaining exactly one correlated mismatch
event. Replay must still raise PredictionMismatch, preserve the first observation
and complete prediction identity/digests/policy, and never redispatch the backend.
The second context deliberately supplies a now-matching observation to prove it
cannot overwrite the persisted mismatch.

Regression evidence and validation results are recorded in REPAIR-NOTES-57.md.
