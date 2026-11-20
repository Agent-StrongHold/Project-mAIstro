---
inventory-delta:
  packages/maistro-core/tests: +2
---

# CI repair: cover the two seams the diff-coverage gate named (#2367)

The Coverage gate failed at 6a9cefeec3 on two changed seams this PR itself
introduced but only half-proved:

- `packages/maistro-core/src/maistro/graph/durable_runs/execution_store.py:542-543`
  — the `AttemptNotFound` → `RunIntegrityError` translation in
  `_settle_one_canonically` had no test: every existing reclaim test used a
  store that returns a row or `None`, never one that reports the canonical
  identity missing.
- `packages/maistro-core/src/maistro/runs/store.py:1814` — the in-memory batch
  re-check under the dict write authority had one arc (`1814→continue`, a
  renewal landing between the doomed snapshot and the write) never exercised,
  because the in-memory loop has no await point a real race could interleave
  with.

## Collected node IDs

`packages/maistro-core/tests/graph/durable_runs/test_canonical_execution_store.py`
(+1):

- A canonical Attempt missing at reclaim is an integrity error
  (`_VanishingAttemptRunStore` raises `AttemptNotFound` from the exact-ID seam;
  the adapter must surface it as `RunIntegrityError`, not absorb it)

`packages/maistro-core/tests/runs/test_reclaim_expired_attempt_exact_id.py`
(+1):

- Batch reclaim skips an Attempt renewed between snapshot and write (in memory)
  — the predicate is stubbed per call (admit on the snapshot read, refuse on
  the re-check) rather than raced on wall-clock timing, so the test pins the
  guard's structure, not the scheduler's speed

Both tests assert outcomes over the store's durable state (nothing written,
nothing returned) rather than internal call counts alone, and both fail against
the regression they name: removing the translation re-raises `AttemptNotFound`
out of the recovery sweep; removing the re-check writes a renewed Attempt and
returns it.
