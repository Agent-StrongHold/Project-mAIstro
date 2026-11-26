---
inventory-delta:
  packages/maistro-core/tests: +18
---
# 984-explore-waves-settlement-race

**+18 in one suite** — the M7-A8 settlement-race repair round added
concurrency/idempotency coverage on top of the base M7-A8 wave contract:
atomic wave-winner settlement under a per-Run lock, rejection of re-fanning
an already populated wave under the same lock, and durable (Run-derived)
rejection enforcement even when the caller omits or passes a stale
`rejected_theses` list (parametrized over caller-supplied vs. omitted input).
