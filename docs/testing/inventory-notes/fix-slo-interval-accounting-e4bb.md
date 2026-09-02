---
inventory-delta:
  packages/maistro-core/tests: +33
---
# fix-slo-interval-accounting-e4bb

SLO interval accounting introduces thirty-four collected boundary, property,
overlap, lookback, pruning, timestamp, and finite-input cases. Four of those
replace the prior single negative-downtime node, so the resulting
`packages/maistro-core/tests` inventory delta is +33.
