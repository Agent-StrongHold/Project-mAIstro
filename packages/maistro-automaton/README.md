# maistro-automaton

Deterministic autonomous-actor machinery: the tickable skeleton of a
self-moving actor with no identity, no platform imports, and no opinions
about what the actor wants.

- **Reactor / TickReactor** — the pulse; handlers see a monotonic tick count
- **DriveSpec / compute_drives** — stable facets × fast mood → drive pressure
- **Producer / ThresholdGate** — threshold-gated candidate generators
- **MotivationArbiter** — one action per tick, highest drive wins, refractory
  periods against churn
- **CageCheckpoint / CageVerdict** — deterministic gates that return
  structured verdicts instead of raising
- **Episode / EpisodeSink** — the persistence port; hosts decide what
  durability means

Turing is one instantiation of this machinery; the merge-train tender is
another; neither is the library. See
`docs/specs/SPEC-282-automaton-actor-machinery.md`.
