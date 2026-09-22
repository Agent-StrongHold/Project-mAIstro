---
inventory-delta:
  packages/maistro-automaton/tests: +17
---
# agent-automaton-machinery

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

New suite registering the `maistro-automaton` package (SPEC-282): 17 tests
covering the six extracted actor-machinery contracts — drive computation
(facet/mood terms, clamping, typed mood-contract failure), threshold gates,
the motivation arbiter (highest-drive-per-tick, per-key refractory against
churn), cage verdicts (frozen, first-block-wins), the tick reactor, and the
episode-sink port. All tests are deterministic via injected clocks and
explicit ticks; the package has zero runtime dependencies by design.
