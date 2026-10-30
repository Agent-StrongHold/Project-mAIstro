---
inventory-delta:
  packages/maistro-design/tests: 9
---

# Bound escaped consistency marker matching time

Nine regression cases cover both dynamic matching sinks under the #2288
literal-escape contract, timeout propagation, literal metacharacter matching,
negation attribution, early-exit before later match work, oversized-marker
refusal before compile, and an escaped adversarial pattern that must not be
interpreted as a regular expression. The two budget-instrumentation cases
failed against unbounded matching before the fix; all nine pass afterward.
Timeouts abort evaluation rather than silently returning a passing verdict.
