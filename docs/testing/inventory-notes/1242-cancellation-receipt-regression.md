---
inventory-delta:
  packages/maistro-core/tests: +4
  packages/hive-conductor/backend/tests: +0
---
# Issue #1242 cancellation receipt regression

Adds `packages/maistro-core/tests/runs/test_cancellation_receipt_1242.py`, four
regressions over the real `RunExecutionService` and in-memory store. They pin
the receipt contract the implementation commit introduced: a cancellation of
an Attempt held under a remote worker's live lease reports `STOP_PENDING` with
`stop_confirmed=False` (not a false stop), a repeat cancellation keeps that
answer, a queued Run with no physical try reports `STOP_CONFIRMED`, and the
Run API's fence agrees with the receipt's fence.

Mutation check: forcing the classifier to report `STOP_CONFIRMED` for a live
remote try fails the two remote-owner regressions; the production file was
restored byte-for-byte afterwards.
