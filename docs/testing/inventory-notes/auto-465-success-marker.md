---
inventory-delta:
  tests/: +1
---
# auto-465 success marker

The shipped-surface detector now treats literal boolean `success: true` and
`ok: true` response objects as success-shaped fake-success candidates when the
handler performs no real work. One regression test proves a multi-statement
boolean-success fixture is rejected from a production-enabled canonical
classification.
