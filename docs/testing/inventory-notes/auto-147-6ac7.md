---
inventory-delta:
  packages/maistro-core/tests: +10
---
# auto-147-6ac7

Adds the delegation child-run regressions: a cross-instance resume proves
the child completes through a yielded and completed canonical Attempt rather
than direct Run terminalization, while an inline subgraph remains request
context on an opaque child node because the A2A transport sends only the text
task. The broader issue coverage also records scope refusal, child attribution
and lifecycle edge cases; the separate delegation receipt, direct-admission,
and factory-wiring notes explain those focused additions.
