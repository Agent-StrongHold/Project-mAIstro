---
inventory-delta:
  formal: +3
  tests: +4
---
# 343-hypothesis-nightly-closeout

Closeout for #343 adds three collected formal node IDs while making the nightly Hypothesis profile and deterministic replay policy explicit, plus four focused root regression node IDs that prove the selected mode actually controls Hypothesis settings and that per-test settings cannot silently defeat the suite policy.

These are behavior/evidence additions, not count banking: the suite-inventory delta records the new collected tests so CI can continue detecting unexpected collection loss or growth.
