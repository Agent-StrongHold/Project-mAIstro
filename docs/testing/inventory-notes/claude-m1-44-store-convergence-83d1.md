---
inventory-delta:
  packages/maistro-core/tests: +4
---
# claude-m1-44-store-convergence

**`tests/graph/durable_runs/test_canonical_identity.py` (+4)** — graph
execution obtains its Run from the canonical store rather than minting one in
memory:

- a Run the durable graph executed is findable in the canonical store, with its
  scope and `executor` provenance — the symptom #44 exists to remove;
- the identity is the store's, so the record's `run` is a projection of a row
  that already exists rather than an id minted first and persisted after;
- without a `run_store` the previous behaviour is unchanged, so a caller with
  no spine wired still runs rather than failing to start;
- a pinned `run_id` still wins, because an already-admitted Run being executed
  must not be given a second identity.
