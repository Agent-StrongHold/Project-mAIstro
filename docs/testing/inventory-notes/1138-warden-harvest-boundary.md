---
inventory-delta:
  packages/maistro-rsi/tests: +16
---
# Issue #1138 Warden harvest boundary

Adds collected cases covering recursive RSI harvest admission: ordinary and
structured payload forms, model-call refusal, unavailable-policy fail-closed
behavior, audit correlation/redaction, canonical event persistence, digest
evidence, nested keys, synchronous active-loop refusal, and saved-patch resume
refusal for hostile or unavailable Warden policy.
