---
inventory-delta:
  packages/maistro-core/tests: +12
---

Adds coverage for the M4-B3 Learning record's epistemic qualification: structured `works_when`/`avoid_in` and `evidence_run_ids`/`evaluation_ids` union across dedup and rewording (the outgoing producer survives in evidence, in-memory and on the SQLite twin); `EpistemicType` breaks keyword ties in retrieval via `EPISTEMIC_BONUS` without ever overriding relevance; the CoinSwarm wisdom JSON import (`learning_from_wisdom`) maps `excels_in`/`avoid_in`/`confidence` onto a REPORTED learning that still lacks promotion evidence; and the SQLite twin round-trips every epistemic field, consolidates evidence on dedup, re-measures confidence in `mark_outcome`, and upgrades a pre-M4-B3 database in place with legacy rows reading observed/unmeasured.
