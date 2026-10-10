---
inventory-delta:
  packages/maistro-design/tests: 8
---

# Bound escaped consistency marker matching time

Eight regression cases cover both dynamic matching sinks under the #2288
literal-escape contract, timeout propagation, literal metacharacter matching,
negation attribution, early-exit before later match work, oversized-marker
refusal before compile, and an escaped adversarial pattern that must not be
interpreted as a regular expression. The two budget-instrumentation cases
failed against unbounded matching before the fix; all eight pass afterward.
Timeouts abort evaluation rather than silently returning a passing verdict.
