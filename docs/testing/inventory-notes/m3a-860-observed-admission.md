---
inventory-delta:
  tests/: +12
---

# #860 — admission evidence must observe a canonical Run

Twelve HTTP-probe regression cases in `tests/test_soak_promotion_gates.py`
cover all-conflict and empty probes, non-concurrent submission, missing/null/
blank/non-string identities, partial invalid receipts, a second identity hidden
in a HTTP 200 replay, successful admission/replay/conflict receipts and partial
HTTP failure. They exercise the actual concurrent probe through HTTPX transport
and propagate its result into the promotion evaluator.

Fresh reproduction before repair: twelve HTTP 409 responses, zero Run IDs,
`cause=ok`, `ok=true`. H1 now requires at least two submissions, a canonical
identity on every successful receipt, exactly one distinct observed identity,
and only accepted/replay/conflict responses. HTTP 200 replay IDs participate in
deduplication rather than hiding an extra Run. No admission/store authority is
changed. These tests validate the oracle, not physical work or a live RC soak.
