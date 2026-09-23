---
inventory-delta:
  tests/: +7
---
# auto-465 fetch options

The shipped-surface regression suite adds two collected tests for a mutating
`fetch` whose literal `RequestInit` object is hoisted into a named variable,
and for an unresolved named options object that must remain matrix-required.
The starting repair branch also had five collected root-suite nodes missing
from its recorded ledger delta (`3449` expected versus `3454` collected); this
single note reconciles that existing drift and the two new nodes to `3456`.
