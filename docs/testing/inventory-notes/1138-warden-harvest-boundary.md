---
inventory-delta:
  packages/maistro-rsi/tests: +12
---
# Issue #1138 Warden harvest boundary

Adds ten collected cases covering recursive RSI harvest admission: ordinary and
structured payload forms, model-call refusal, unavailable-policy fail-closed
behavior, audit correlation/redaction, digest evidence, nested keys, and the
synchronous adapter's active-loop refusal.
