---
inventory-delta:
  tests/: +16
---
# Issue metadata integrity

Sixteen root-suite tests cover explicit hierarchy parsing, conflicting parents,
cycles, stale-source refusal, live parent refusal, durable write journaling,
forward/reverse verification, repeat-run idempotence, pagination and API failure, new ownership comments and required milestone classification.

The workflow also executes this isolated stdlib suite without product services.
