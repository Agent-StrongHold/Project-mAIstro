---
inventory-delta:
  tests/: +8
---
# M1 #463 golden behavioral baseline evidence

Adds exactly eight collected root-suite tests in
`tests/test_m1_golden_baselines.py`. No existing test is removed or
parametrized.

The tests prove required-product coverage, byte-level fixture immutability,
fail-closed fixture validation, evidence-test traceability, ID uniqueness,
self-consistency of captured examples, and two planted semantic incompatibilities:
Builders retry changing logical Run identity and a scheduled execution losing
its durable Run identity.
