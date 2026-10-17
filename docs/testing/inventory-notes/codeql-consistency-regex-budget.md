---
inventory-delta:
  packages/maistro-design/tests: 7
---

# Bound caller-authored consistency regex execution

Seven regression cases cover both dynamic matching sinks, timeout propagation,
legitimate regex syntax, invalid-pattern literal fallback, negation attribution,
and real adversarial backtracking. The two budget-instrumentation cases failed
against the original implementation before the fix; all seven pass afterward.
Timeouts abort evaluation rather than silently returning a passing verdict.
