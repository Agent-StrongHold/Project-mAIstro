---
id: SPEC-278
title: "CapabilityProfile schema, EMA skill-score updater, and surfacing rules"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-07-04
substrate:
  - maistro-engine#ADR-070426-c4b2
related:
  - maistro-engine#ADR-062226-674b
  - maistro-engine#SPEC-184
  - maistro-engine#ADR-058
implements: []
supersedes: []
blocks: []
blocked-by:
  - maistro-engine#ADR-070426-c4b2
contracts:
  - boundary
  - behavioral
tests: []
layer: Agents
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-07-04
---

# SPEC-278: CapabilityProfile Schema and Updater

## Context

ADR-070426-c4b2 decides *that* `CapabilityProfile` exists — three orthogonal dimensions
(permission, skill, cost) keyed by `(capability, intent_class)`, blocked entries never surfaced.
This spec fixes the concrete dataclasses, the storage protocol seam, the EMA update formula that
converges declared skill priors toward measured outcomes, and the surfacing rule as testable
acceptance criteria.

## Goals

1. A frozen, mypy-strict dataclass schema for `CapabilityProfile` / `CapabilityEntry` /
   `SkillScore` / `CostVector` / `Permission`, importable from `maistro.capabilities.profile`.
2. A skill-score updater that consumes eval-outcome events and updates the matching
   `(agent, capability, intent_class)` entry via EMA, per-scope isolated.
3. A storage protocol seam (`CapabilityProfileStore`) with an in-memory implementation, following
   the existing protocol-driven-DI pattern (no direct persistence coupling in the updater).
4. Surfacing rule: `visible_entries()` never returns a `BLOCKED` entry, enforced by a property-style
   test, not just a happy-path unit test.

## Non-goals

- The reasoning router that consumes profiles for self-execute/delegate/decline (ADR-070426-c4b2
  §4) — future spec.
- Skill-score decay — this spec ships "no decay in v1" per AC-5; a decay function is future work
  once production evidence justifies narrowing the constant (ADR-062226-674b's tunability ladder).
- PostgreSQL-backed `CapabilityProfileStore` — the protocol is defined here; a persistent
  implementation follows the same pattern as `persistence/` stores elsewhere in maistro-core, as a
  follow-up.
- Cold-start exploration policy for skill scores with zero samples — open question, not resolved
  here.

## Design

### 1. Schema (`maistro.capabilities.profile`)

```python
"""CapabilityProfile: per-agent (capability, intent_class) permission/skill/cost model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Permission(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class CostVector:
    """Measured cost dimensions. All fields default to 0.0 / empty until observed."""

    standing: dict[str, float] = field(default_factory=dict)  # cpu, mem, replicas_min
    cold_start_ms: float = 0.0
    per_call_compute: float = 0.0
    per_call_tokens: float = 0.0
    tool_fees: float = 0.0
    overhead: float = 0.0


@dataclass(frozen=True)
class SkillScore:
    """Intent-conditional competence. `value` starts as the declared prior."""

    value: float  # clamped to [0.0, 10.0] at construction
    sample_count: int = 0

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 10.0:
            raise ValueError(f"SkillScore.value must be in [0, 10], got {self.value}")


@dataclass(frozen=True)
class CapabilityEntry:
    capability: str
    intent_class: str  # "*" for intent-agnostic capabilities
    permission: Permission
    skill: SkillScore
    cost: CostVector


@dataclass(frozen=True)
class CapabilityProfile:
    agent_name: str
    scope: str = "global"  # org/team scope key — see AC-8 (per-scope isolation)
    entries: tuple[CapabilityEntry, ...] = ()

    def visible_entries(self) -> tuple[CapabilityEntry, ...]:
        return tuple(e for e in self.entries if e.permission is Permission.ALLOWED)

    def entry(self, capability: str, intent_class: str) -> CapabilityEntry | None:
        for e in self.entries:
            if e.capability == capability and e.intent_class == intent_class:
                return e
        return None
```

`ValidationError` (reusing `maistro.types.errors.ConfigError` — no new error type) is raised by a
`validate_profile()` module function, not `__post_init__`, so a profile missing a dimension for a
declared `(capability, intent_class)` pair fails at load time with a field-identifying message
(AC-2), while `SkillScore`'s own bounds check stays a construction-time invariant (AC-1's
"validated without errors" path exercises both).

### 2. EMA skill-score updater (`maistro.capabilities.profile_updater`)

```python
def update_skill_score(
    current: SkillScore,
    outcome_score: float,   # 0.0-10.0, from an eval outcome event
    *,
    alpha: float = 0.2,     # ConfigStore-backed per ADR-062226-674b's "Tunable" stage; ships as a default
) -> SkillScore:
    """EMA: new = alpha * outcome + (1 - alpha) * current. sample_count increments."""
    new_value = alpha * outcome_score + (1 - alpha) * current.value
    return SkillScore(value=new_value, sample_count=current.sample_count + 1)
```

- **No outcomes → no change.** The updater is only ever invoked by an outcome-event consumer; a
  capability with zero outcomes keeps `sample_count=0` and its declared-prior `value` untouched
  (AC-2 in the source stories; no decay path exists in this spec, matching OQ-CAP-01's deferral).
- **`alpha` is Tunable, not hardcoded.** Per ADR-062226-674b's constant-tunability ladder, `alpha`
  ships as a `ConfigStore`-backed value with a documented default (`0.2`), not a bare module
  constant — an admin can widen or narrow convergence speed per deployment without a code change.
  It only moves to Enumerated/Locked once production evidence narrows the useful range.
- **Convergence, not snap-to-latest.** A single outlier outcome moves the score by at most
  `alpha` of the gap to the prior, not to the outcome itself — this is why 10+ outcomes are needed
  to meaningfully converge (AC-3), and why the update is idempotent-safe against one bad eval run.

### 3. Outcome event shape and per-scope isolation

The updater consumes `CapabilityOutcomeEvent`:

```python
@dataclass(frozen=True)
class CapabilityOutcomeEvent:
    agent_name: str
    capability: str
    intent_class: str
    scope: str  # matches CapabilityProfile.scope — org/team isolation boundary
    score: float  # 0.0-10.0, from the eval substrate (out of scope here; consumed as given)
```

The updater looks up the `(agent_name, capability, intent_class, scope)` tuple's entry via
`CapabilityProfileStore.get(agent_name, scope)`, applies `update_skill_score`, and writes back
through the same store — never touching an entry in a different `scope` (AC-4). This is the same
soft-scope-axis pattern already used elsewhere in maistro-core (`global → org → team → user →
agent → session`); it is not Stronghold's hard tenant boundary, and does not need to be — a
CapabilityProfile's `scope` field is a lookup key, not a security boundary enforced here (ADR-068
already owns permission's enforcement path).

### 4. Storage protocol seam

```python
class CapabilityProfileStore(Protocol):
    async def get(self, agent_name: str, scope: str = "global") -> CapabilityProfile | None: ...
    async def put(self, profile: CapabilityProfile) -> None: ...
```

`InMemoryCapabilityProfileStore` ships in this spec (mirrors `InMemoryLearningStore`'s shape). A
PostgreSQL-backed store follows the `persistence/` package's existing pattern as a follow-up — not
blocking this spec, since the updater and schema are usable against the in-memory store alone for
the round-trip ship gate.

### 5. Surfacing rule enforcement

`visible_entries()` (schema, §1) is the only sanctioned read path for anything that hands a
capability list to a reasoning agent. A lint/test convention (not new machinery): any future
router or context-builder code that iterates `CapabilityProfile.entries` directly instead of
`visible_entries()` is a code-review flag, matching the existing "all input is untrusted" boundary
discipline — a blocked capability must never appear in a prompt, tool list, or trace visible to the
LLM side of the boundary.

## Acceptance criteria

- **AC-1**: Given a `CapabilityProfile` with all three dimensions populated for every declared
  entry, When `validate_profile()` runs, Then it returns without raising.
- **AC-2**: Given a profile entry missing the skill dimension (constructed with a sentinel/`None`
  before defaulting), When `validate_profile()` runs, Then it raises `ConfigError` naming the
  missing field and the `(capability, intent_class)` pair.
- **AC-3**: Given a profile with intent-conditional skill scores
  (`{summary: 4, report: 8, prose: 2}` as three separate `CapabilityEntry` rows), When
  `.entry("x", "summary")` is called, Then it returns the entry with `skill.value == 4`.
- **AC-4**: Given a `CapabilityEntry.cost` populated with `standing={"cpu": 1.0, "mem": 512}`,
  When the cost vector is read, Then `standing` round-trips exactly (no field dropped/renamed).
- **AC-5**: Given a `CapabilityEntry` with `permission=Permission.BLOCKED`, When
  `profile.visible_entries()` is called, Then that entry is absent from the result (not present
  with any score).
- **AC-6**: Given a `SkillScore` and a stream of `CapabilityOutcomeEvent`s for the matching tuple,
  When `update_skill_score` runs once per event, Then the resulting `value` moves monotonically
  toward the outcome scores' mean and `sample_count` increments by exactly 1 per call.
- **AC-7**: Given zero outcome events for a `(capability, intent_class)` pair, When the updater
  pipeline runs, Then the entry's `skill.value` and `sample_count` are unchanged from the declared
  prior.
- **AC-8**: Given 10+ outcome events with scores clustered near a value distinct from the prior,
  When the updater has processed all of them, Then the resulting `value` is closer to the outcomes'
  mean than the original prior was.
- **AC-9**: Given outcome events tagged with two different `scope` values for the same
  `agent_name`/`capability`/`intent_class`, When the updater processes both streams, Then each
  scope's stored entry reflects only its own events (no cross-scope bleed).
- **AC-10**: Given a `CapabilityProfile` serialized via the store's `put()` then reloaded via
  `get()`, When compared to the original, Then all entries and dimensions are equal
  (round-trip, the epic-02 ship gate).

## Test plan

| AC   | Test path                                              | Test function                                   | Tier     |
|------|---------------------------------------------------------|--------------------------------------------------|----------|
| AC-1 | `packages/maistro-core/tests/capabilities/test_profile_schema.py` | `test_full_profile_validates`                | critical |
| AC-2 | `packages/maistro-core/tests/capabilities/test_profile_schema.py` | `test_missing_skill_raises_validation_error`  | critical |
| AC-3 | `packages/maistro-core/tests/capabilities/test_profile_schema.py` | `test_intent_conditional_skill_lookup`        | critical |
| AC-4 | `packages/maistro-core/tests/capabilities/test_profile_schema.py` | `test_cost_vector_round_trips_standing`       | happy    |
| AC-5 | `packages/maistro-core/tests/capabilities/test_profile_schema.py` | `test_blocked_capability_omitted_from_visible`| critical |
| AC-6 | `packages/maistro-core/tests/capabilities/test_profile_updater.py`| `test_ema_updates_skill_from_outcome`         | critical |
| AC-7 | `packages/maistro-core/tests/capabilities/test_profile_updater.py`| `test_no_outcomes_preserves_prior`            | happy    |
| AC-8 | `packages/maistro-core/tests/capabilities/test_profile_updater.py`| `test_convergence_after_many_outcomes`        | happy    |
| AC-9 | `packages/maistro-core/tests/capabilities/test_profile_updater.py`| `test_per_scope_isolation`                    | critical |
| AC-10| `packages/maistro-core/tests/capabilities/test_profile_store.py`  | `test_profile_round_trips_through_store`      | critical |

- **Unit**: schema validation branches (AC-1, AC-2), intent-conditional lookup (AC-3), cost-vector
  field fidelity (AC-4), EMA arithmetic in isolation (AC-6, AC-7, AC-8).
- **Contract**: `CapabilityProfileStore` protocol — `InMemoryCapabilityProfileStore` conforms;
  a future PostgreSQL store must pass the same contract suite before it ships.
- **Integration**: outcome-event stream → updater → store → reload, exercising the full round-trip
  ship gate (AC-10) and scope isolation (AC-9) together.
- **Property** (`formal/`, per repo convention): "`visible_entries()` never returns a `BLOCKED`
  entry, for any profile" — generalizes AC-5 beyond the hand-written fixture.

## Open questions (carried from source epic, not resolved here)

- Skill-score decay function for capabilities with stale/no recent outcomes (OQ-CAP-01) — no
  decay in this spec; revisit once production data exists to justify a specific decay curve.
- Cost-vector aggregation across nested/delegated calls (OQ-CAP-02) — this spec covers a single
  agent's own cost vector, not roll-up across an A2A delegation chain.
- Cold-start exploration policy for zero-sample skill scores (OQ-CAP-03) — deferred to the future
  reasoning-router spec (ADR-070426-c4b2 §4).

## References

- [ADR-070426-c4b2: CapabilityProfile](../adr/ADR-070426-c4b2-capability-profile.md)
- [ADR-062226-674b: Constant tunability ladder](../adr/ADR-062226-674b-constant-tunability-ladder.md)
- [SPEC-184: Modular capability platform](SPEC-184-modular-capability-platform.md)
- [ADR-058: A2A delegation protocol](../adr/ADR-058-a2a-delegation-protocol.md)
- Seams: `capabilities/types.py`, `types/errors.py` (`ConfigError`), `memory/learnings/store.py`
  (`InMemoryLearningStore` — the store shape this spec's `InMemoryCapabilityProfileStore` mirrors)
