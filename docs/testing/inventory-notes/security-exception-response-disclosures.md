---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
  packages/maistro-canvas/tests: +1
---

# Security: exception response disclosures

Seven new Conductor cases cover health/router diagnostics, stored evolution
errors, unexpected/canonical/unavailable evolution failures, intentional HTTP
validation, and RSI policy failures. One new Canvas case preserves the 409
idempotency conflict contract without returning internal exception diagnostics.
The existing DAG canonical-failure test now injects credential-shaped diagnostics
at both run and node level and verifies the complete response stays clean.

Negative control: all nine selected regression cases fail on the original
implementation at cc6e4899 (including the existing DAG case strengthened here).
Run identity and status remain public; internal diagnostic strings do not.
