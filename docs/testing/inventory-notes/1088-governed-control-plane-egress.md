---
inventory-delta:
  packages/hive-conductor/backend/tests: +5
  packages/maistro-bootstrap/tests: +3
---
# Governed evaluator and provider health egress

Adds three focused regression cases for issue #1088: benchmark evaluation
records a correlated canonical Invocation with usage and response-format
parity; provider activation registration is Provider-internal while its health
completion records an Invocation without persisting the transient provider
secret; and an evaluator missing canonical Run scope reports an authorization
failure rather than pretending evaluation succeeded. Two bootstrap cases prove
ordinary model selection reads only the persisted operator cache/default and
never refreshes the physical diagnostic probe implicitly.
