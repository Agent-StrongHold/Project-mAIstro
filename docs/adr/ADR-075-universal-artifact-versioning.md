---
id: ADR-075
title: "Universal Artifact Versioning and Release Channels"
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-30
substrate:
  - maistro-engine#ADR-006
  - maistro-engine#ADR-053
  - maistro-engine#ADR-069
implements: []
related:
  - maistro-engine#ADR-007
  - maistro-engine#ADR-070
  - maistro-engine#ADR-031
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
  - boundary
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-30
---

# ADR-075: Universal Artifact Versioning and Release Channels

**Status:** Proposed
**Date:** 2026-05-30
**Establishes one versioning model** for every runtime artifact the engine produces, evolves, and
executes, so that learn-forward evolution and mission-critical stability can coexist without one
silently corrupting the other.

---

## Context

The engine has many *kinds* of runtime artifact — skills, tools, agents, recipes, DAGs, policies —
and several independent forces that mutate them: human edits, maistro-evolve fitness optimization
(ADR-006), learned/composed changes (ADR-069), and skill-forge generation. Today each kind handles
versioning ad hoc (or not at all). That creates two failures: a consumer cannot reliably pin or roll
back to a known-good revision, and a learned improvement to a low-stakes flow can drift into a
mission-critical path with no gate. We need one uniform versioning contract that makes both
properties hold at once: continuous evolution *and* explicit, gated promotion before anything
mission-critical changes.

This is distinct from versioning the `maistro-core` **library** (the pip package) — see Out of scope.

## Decision

Every runtime artifact — skill, tool, agent, recipe, DAG, policy — is versioned **uniformly** under a
single contract. Two invariants hold for all kinds:

1. **Rollbackability** — any prior version of an artifact is addressable and restorable at any time.
2. **Learn-forward evolution** — artifacts continuously produce new versions from fitness/outcome
   signals, but a new version never *silently* becomes the one a mission-critical caller runs.

### Identity

Every artifact reference is `name@version + channel`. `version` is semver (`major.minor.patch`).
`channel` is one of the release channels below. A reference without an explicit version resolves
through the consumer's chosen strategy against the chosen channel.

### Consumer strategies (per artifact reference)

A consumer picks one strategy per reference:

1. **LOCK** — pin an exact `name@version`. Never moves. Maximum stability.
2. **DRIFT-GATE-MAJOR** — semver-range style: accept point releases (`patch`/`minor` drift)
   automatically, but **hold at integer/major boundaries** until the consumer re-opts in. The common
   default for production references.
3. **BEST-AVAILABLE** — always run the latest version on a *dev* channel (alpha/beta/canary/tester).
   For experimentation and the evolution feedback loop.

### Release channels

```
alpha  ->  beta  ->  canary  ->  tester  ->  stable
\_______________  ___________/              \__ mission-critical __/
                \/
        dev channels: AUTO-ADVANCE
```

- **alpha -> beta -> canary**: artifacts **auto-advance** through the dev channels when fitness /
  outcome metrics pass (driven by maistro-evolve, ADR-006). No human in the loop here.
- **tester**: staging hold for pre-stable validation.
- **stable** (mission-critical): promotion into `stable` requires **explicit admin/owner sign-off**.
  Learned drift can reach `canary`/`tester` on its own, but crossing into `stable` is always a
  deliberate human act. This is the gate that keeps learn-forward from corrupting mission-critical
  usage.

### Interface

```python
class ArtifactRef(BaseModel):
    name: str
    version: str                  # semver "1.4.2"
    channel: Literal["alpha", "beta", "canary", "tester", "stable"]

class ResolveStrategy(str, Enum):
    LOCK = "lock"                       # exact version, never moves
    DRIFT_GATE_MAJOR = "drift_gate"     # auto point releases, hold at major
    BEST_AVAILABLE = "best_available"   # latest on the named dev channel

class ArtifactRegistry(Protocol):
    def resolve(self, name: str, *, strategy: ResolveStrategy, channel: str) -> ArtifactRef: ...
    def rollback(self, name: str, to: str) -> ArtifactRef: ...      # any prior version, always
    def promote(self, ref: ArtifactRef, to: str, *, approved_by: str | None) -> ArtifactRef: ...
    #   to in {beta,canary} -> auto-allowed on passing metrics; to == "stable" -> approved_by required
```

A `promote(..., to="stable")` with `approved_by is None` is rejected. Dev-channel advancement is
driven by metrics, not by callers.

## Acceptance criteria

- [ ] Every runtime artifact kind (skill, tool, agent, recipe, DAG, policy) is addressable as
      `name@version + channel` through one registry contract.
- [ ] `rollback(name, to=<any prior version>)` restores that version regardless of current channel.
- [ ] A consumer reference can declare LOCK, DRIFT-GATE-MAJOR, or BEST-AVAILABLE, and resolution
      honors it (property test: LOCK never returns a different version; DRIFT-GATE-MAJOR never crosses
      a major boundary without re-opt-in).
- [ ] Artifacts auto-advance alpha -> beta -> canary on passing fitness/outcome metrics, with no
      human step, and the advancing event is recorded.
- [ ] Promotion to `stable` requires an explicit admin/owner sign-off; an unsigned promotion to
      `stable` is rejected.
- [ ] A mission-critical (stable) consumer never receives a learned/evolved version that was not
      explicitly promoted to `stable`.

## Consequences

- A single versioning contract replaces per-kind ad-hoc schemes; rollback and pinning are uniform.
- maistro-evolve gets a defined target — it advances artifacts on the dev channels, and stops at the
  `stable` boundary by construction.
- Mission-critical paths are protected from silent drift without freezing evolution elsewhere.
- Consumers carry an explicit strategy per reference; references that omit one fall back to a
  conservative default (DRIFT-GATE-MAJOR on `stable`).

## Out of scope

- **The `maistro-core` library's own versioning.** The pip package is pre-1.0 / break-freely
  (`0.x` semver + CHANGELOG; downstream consumers pin an exact version). That is a packaging concern,
  not runtime-artifact versioning, and is deliberately *not* governed by this ADR — do not conflate
  the two.
- The storage schema / backing store for version history and channel state.
- The exact fitness/outcome metric thresholds that trigger dev-channel auto-advance (a maistro-evolve
  tuning detail, ADR-006).
- Cross-artifact dependency resolution (a skill that requires a specific tool version).
