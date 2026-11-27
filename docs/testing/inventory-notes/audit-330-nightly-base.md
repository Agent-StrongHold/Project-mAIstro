---
inventory-delta:
  tests/: +4
---
# Nightly mutation provenance (#330)

The first shard-level `RATCHET_BASE_REV` declaration introduced two parametrized nodes in `tests/test_ratchet_base_rev_policy.py` (each of its two `_declarations()` parametrizations). CI job 140496318242 measured exactly +2: 6707 expected, 6709 collected. Both candidate and same-base develop had identical Python tests; the YAML declaration itself changes collection. The publishing job now has a second declaration, expected to contribute another two nodes under the same existing tests (+4 total). Revalidate exact count on new CI; no unrelated debt is banked.
