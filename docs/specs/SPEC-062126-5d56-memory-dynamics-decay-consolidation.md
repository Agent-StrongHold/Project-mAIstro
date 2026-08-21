---
id: SPEC-062126-5d56
title: "Memory dynamics follow-up: pluggable decay strategy and LLM-mediated contradiction resolution (ADR-080)"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-06-21
substrate:
  - maistro-engine#ADR-013
  - maistro-engine#ADR-016
  - maistro-engine#ADR-080
  - maistro-engine#SPEC-240
  - maistro-engine#SPEC-241
implements:
  - maistro-engine#ADR-080
related:
  - maistro-engine#ADR-057
  - maistro-engine#SPEC-242
  - maistro-engine#SPEC-243
  - maistro-engine#SPEC-248
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/memory/test_dynamics.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-062126-5d56: Memory dynamics follow-up — decay strategy and contradiction resolution

## Context

ADR-080 specifies decay+reinforcement (A), consolidation (B), cross-scope consent (C), and
hybrid retrieval ranking (D). Three of these four are already implemented:
SPEC-240 (`memory/episodic/tiers.py`) ships the concrete decay/feedback mechanics,
SPEC-241 (`memory/episodic/consolidation.py`) ships merge/contradiction-flagging consolidation,
SPEC-242 (`memory/episodic/sharing.py`) ships cross-scope consent, and SPEC-243
(`memory/episodic/ranking.py`) ships the hybrid ranking formula. This SPEC does **not**
re-specify any of those — it only closes the two gaps those SPECs explicitly left open:

1. SPEC-240's `tick_decay` hardcodes an exponential curve inline; it is not swappable.
   ADR-080's own follow-up note calls for a pluggable `DecayStrategy` protocol.
2. SPEC-241's `apply_contradiction` always lowers both sides and flags for human review —
   there is no LLM-mediated auto-resolution path. ADR-080's follow-up note calls for
   auto-resolution gated by a confidence threshold using the same cold-start-decay shape
   already used by RLPHD's theta schedule (SPEC-248, `security/sentinel/rlphd.py`).

## Goals

- Extract `DecayStrategy` as a `Protocol` and refactor SPEC-240's `tick_decay` to call it,
  with `ExponentialDecay` (the existing curve) as the default — no behavior change for
  existing callers, just made swappable.
- Add a `ContradictionResolver` protocol and `ContradictionResolutionThreshold` schedule
  that `consolidate_pair()` (SPEC-241) can optionally consult: if a resolver is supplied and
  its verdict confidence clears the threshold, auto-apply instead of flagging for review.
  Absent a resolver, behavior is unchanged from SPEC-241 (always flag).

## Non-goals

- Re-specifying decay/feedback mechanics (SPEC-240), consolidation/merge (SPEC-241),
  cross-scope consent (SPEC-242), or retrieval ranking (SPEC-243) — those are implemented
  and unchanged by this SPEC.
- The actual LLM prompt/model used for contradiction-confidence scoring — left to the
  `ContradictionResolver` implementation.
- A learned or auto-tuned `admin_offset` — explicit per-deployment config, not derived.

## Decision

### `DecayStrategy` protocol

```python
class DecayStrategy(Protocol):
    def decay(self, weight: float, decay_rate: float, elapsed_seconds: float) -> float:
        """Return the weight after elapsed_seconds with no access/feedback."""
        ...

@dataclass(frozen=True)
class ExponentialDecay(DecayStrategy):
    """Default: weight * exp(-decay_rate * elapsed_seconds). Matches SPEC-240's existing curve."""

    def decay(self, weight: float, decay_rate: float, elapsed_seconds: float) -> float:
        return weight * math.exp(-decay_rate * elapsed_seconds)
```

`tiers.py:tick_decay` gains an optional `strategy: DecayStrategy = ExponentialDecay()`
parameter and delegates its curve computation to it. `WEIGHT_FLOOR` clamping (REGRET ≥ 0.6,
WISDOM ≥ 0.9, per ADR-016) stays applied by `tick_decay` itself, after calling
`strategy.decay()` — the strategy never needs to know about tier floors.

### Contradiction resolution

```python
@dataclass
class ContradictionResolutionThreshold:
    """Confidence theta for LLM auto-resolution; same cold-start shape as RLPHD theta
    (SPEC-248, security/sentinel/rlphd.py) — starts unreachable, decays toward a tunable asymptote."""

    samples_seen: int = 0
    admin_offset: float = 0.0  # per-deployment config, operator-tunable

    def theta(self, median_resolution_confidence: float) -> float:
        floor = median_resolution_confidence + self.admin_offset
        start = 1.5  # > 1.0: unreachable since confidence in [0, 1]
        decay_rate = 0.9
        return floor + (start - floor) * (decay_rate ** self.samples_seen)

class ContradictionResolver(Protocol):
    async def resolve(
        self, a: EpisodicMemory, b: EpisodicMemory, threshold: ContradictionResolutionThreshold
    ) -> ContradictionVerdict:
        """LLM-scores a resolution + confidence. Caller (consolidate_pair) auto-applies
        only if confidence >= theta; below-threshold verdicts are NOT applied — both
        memories are lowered + flagged for review per SPEC-241's existing apply_contradiction,
        unchanged."""
        ...
```

`ContradictionVerdict` carries `confidence: float`, `resolution: Literal["merge", "a_wins",
"b_wins", "unresolved"]`, and `reasoning: str` (audit trail if it falls below threshold).
`samples_seen` increments only on auto-applied resolutions (not escalations), so the
threshold tracks "how many times has auto-resolution proven itself," not raw contradiction
volume.

`consolidate_pair()` (SPEC-241) gains an optional `resolver: ContradictionResolver | None =
None` parameter. When `None` (current default), behavior is unchanged: always
`apply_contradiction`. When supplied, `consolidate_pair` awaits `resolver.resolve(...)`;
if `verdict.confidence >= threshold.theta(...)`, it applies the verdict's resolution instead
of flagging, and increments `samples_seen`.

## Acceptance criteria

- [ ] `ExponentialDecay.decay()` produces a monotonically decreasing weight for
      `decay_rate > 0`, `elapsed_seconds > 0`, and matches `tick_decay`'s pre-existing curve
      bit-for-bit (no behavior change for existing callers).
- [ ] `tick_decay(strategy=...)` accepts an injected `DecayStrategy` and uses it instead of
      the inline curve.
- [ ] `ContradictionResolutionThreshold.theta(median)` returns a value `> 1.0` at
      `samples_seen=0` (unreachable) and converges toward `median + admin_offset` as
      `samples_seen -> infinity`.
- [ ] `consolidate_pair(resolver=None)` behaves exactly as SPEC-241 today (always flags).
- [ ] `consolidate_pair(resolver=...)` with `confidence < theta` never auto-applies; both
      memories are lowered + flagged for review, `samples_seen` does NOT increment.
- [ ] `consolidate_pair(resolver=...)` with `confidence >= theta` auto-applies; `samples_seen`
      increments.

## Testing

- `packages/maistro-core/tests/memory/test_dynamics.py` (new): decay-strategy injection
  parity with the existing inline curve, threshold schedule convergence (property-based via
  Hypothesis: theta is monotonically non-increasing in `samples_seen` and bounded below by
  `median + admin_offset`), contradiction auto-apply vs. escalation branching with/without a
  resolver.

## Open questions

- Whether `DecayStrategy` injection should also flow through `on_access`/`on_feedback`
  (SPEC-240), or stay limited to `tick_decay` — left for the implementation PR; `tick_decay`
  is the only caller that runs a time-based curve, so it's the only one that needs it.

## References

- [ADR-080: Memory Dynamics](../adr/ADR-080-memory-dynamics.md)
- [SPEC-240: Memory decay + reinforcement](SPEC-240-memory-decay-reinforcement.md)
- [SPEC-241: Memory consolidation](SPEC-241-memory-consolidation.md)
- `packages/maistro-core/src/maistro/security/sentinel/rlphd.py` — cold-start theta
  schedule precedent (SPEC-248, same shape, different domain).
