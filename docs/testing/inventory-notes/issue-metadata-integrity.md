---
inventory-delta:
  tests/: +19
---
# Issue metadata integrity

Nineteen root-suite tests cover explicit hierarchy parsing, conflicting parents,
cycles, stale-source refusal, live parent refusal, durable write journaling,
forward/reverse verification, repeat-run idempotence, pagination and API failure,
new ownership comments, required milestone classification, mutation limits,
cross-repository inventory, and external-child number collision.

The workflow also executes this isolated stdlib suite without product services.
