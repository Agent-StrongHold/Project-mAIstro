---
id: SPEC-245
title: "Authorization tier ladder + authorize() evaluation order (ADR-068 §B,F)"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-028
  - maistro-engine#ADR-050
  - maistro-engine#ADR-051
  - maistro-engine#ADR-054
implements:
  - maistro-engine#ADR-068
related:
  - maistro-engine#SPEC-246
  - maistro-engine#SPEC-247
  - maistro-engine#SPEC-248
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
  - boundary
tests:
  - packages/maistro-core/tests/security/test_authz_tier_ladder.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-245: Authorization tier ladder + authorize() evaluation order

## Context

ADR-068 §B defines a six-tier gating ladder (`open`, `role/team-auto`, `self-elevation`,
`delegated-approval`, `admin-elevation`, `blocked`) and §F a five-step evaluation order
(classify → authorize → budget → gate → execute). Nothing implementing this exists today:
`maistro.security.sentinel.policy.Sentinel` has no `Tier`, `Principal`, or `AuthzDecision`
type, and no `resolve_tier()`/`authorize()` method. This SPEC scopes the load-bearing core
that SPEC-246 (approver graph), SPEC-247 (elevation flows), and SPEC-248 (RLPHD) build on:
the tier enum, principal model, decision model, and the `authorize()` orchestration with a
**static** (config-driven, non-learned) tier resolution. Approver-set resolution, the actual
self-elevation/2FA signing flows, and RLPHD auto-acting are out of scope here — `authorize()`
returns the tier and `needs` field; SPEC-246/247/248 plug in the mechanics that clear them.

## Goals

- Add `Tier`, `Principal`, `AuthzDecision` to `maistro/types/security.py` (or a new
  `maistro/security/sentinel/authz_types.py`, matching ADR-068's interface sketch).
- Add `resolve_tier(call, principal) -> Tier` to `Sentinel`: looks up the most-specific
  static policy entry for `(action, principal.roles/scopes)`; defaults to `open` for
  `internal`/`reversible` actions (ADR-050) and `self_elevation` for `irreversible` ones
  absent an explicit policy entry.
- Add `async def authorize(call, principal) -> AuthzDecision` to `Sentinel` implementing
  ADR-068 §F steps 1-4 in order, short-circuiting on first deny:
  1. Classify: reversibility (ADR-050) + tier (resolve_tier) + cost (ADR-054) + Warden risk.
  2. Authorize: does `principal`'s role/scope grant the capability at all? Agents are capped
     at `principal.owner`'s authority (`agent authority = own ∩ owner's`).
  3. Budget: ADR-054 hard veto — over-budget short-circuits to `needs="none", authorized=False`
     regardless of tier.
  4. Gate: map the resolved tier to `AuthzDecision.needs` (`none`/`self_elevation`/
     `scoped_2fa`/`delegated`/`admin`). Agents needing `self_elevation` get `scoped_2fa`
     instead (ADR-068 §D — an agent never self-elevates).
- `approver_scope` and `rlphd` fields on `AuthzDecision` exist but are populated as `None`
  in this SPEC (wired by SPEC-246/248 respectively).

## Non-goals

- Approver-graph policy-matrix resolution (`approved-by` lookups) — SPEC-246.
- Self-elevation re-auth flow and the agent scoped-2FA request/signing flow — SPEC-247.
- RLPHD predictor/threshold — SPEC-248.
- Wiring `authorize()` into the hive-conductor `_PROTECTED_OPS` HTTP gate or any MCP/A2A
  boundary — follow-up integration work once SPEC-246/247 exist (this SPEC only adds the
  Sentinel-level primitive).

## Decision

```python
# maistro/security/sentinel/authz_types.py
class Tier(StrEnum):
    OPEN = "open"
    ROLE_AUTO = "role_team_auto"
    SELF_ELEVATION = "self_elevation"
    DELEGATED = "delegated_approval"
    ADMIN = "admin_elevation"
    BLOCKED = "blocked"

@dataclass(frozen=True)
class Principal:
    id: str
    kind: Literal["human", "agent"]
    roles: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    owner: str | None = None  # required when kind == "agent"

@dataclass(frozen=True)
class AuthzDecision:
    tier: Tier
    authorized: bool
    needs: Literal["none", "self_elevation", "scoped_2fa", "delegated", "admin"]
    approver_scope: str | None
    within_budget: bool
    rlphd: Any | None
    reason: str
```

`resolve_tier` reads a static `dict[(action, role_or_scope), Tier]` policy table passed into
`Sentinel.__init__` (no DB-backed policy yet — that's ADR-073's "declarative policy" follow-up,
already tracked as a Tier-2 partial). Default fallback: ADR-050's `reversibility` classification
on the `ToolCall` determines the tier when no explicit policy entry matches (`internal`/
`reversible` → `open`; `irreversible` → `self_elevation`).

`authorize()` is `async` because budget lookup (ADR-054, step 3) is a store call; steps 1, 2,
4 are pure.

## Acceptance criteria

- [x] `authorize()` runs steps 1-4 in order; a property test asserts no `open` or in-set
      `role_team_auto` action ever produces `needs != "none"`.
- [x] An agent principal resolving to `self_elevation` gets `needs == "scoped_2fa"`, never
      `"self_elevation"`.
- [x] Over-budget (`within_budget=False`) forces `authorized=False` regardless of tier —
      elevation tier alone cannot clear it.
- [x] `resolve_tier` falls back to ADR-050 reversibility class when no explicit policy entry
      matches `(action, principal)`.
- [x] An unauthorized principal (step 2 fails) short-circuits before tier/needs is exposed
      in a way that leaks the gated action's existence (no content-bearing fields populated
      beyond `authorized=False`).

## Testing

- `packages/maistro-core/tests/security/test_authz_tier_ladder.py` (new) — unit tests for
  `resolve_tier` fallback behavior, `authorize()` step ordering and short-circuiting, the
  agent-vs-human `needs` divergence, and the budget hard-veto. Property test (Hypothesis)
  for the "open never prompts" invariant.

## Open questions

- Whether the static policy table should live in `AgentConfig` or a new `SentinelPolicy`
  dataclass injected via `Container` — deferred to implementation; either is compatible with
  this SPEC's `resolve_tier` signature.

## References

- `packages/maistro-core/src/maistro/security/sentinel/policy.py`
- `packages/maistro-core/src/maistro/security/warden/detector.py`
- [ADR-068: Unified Authorization & Elevation](../adr/ADR-068-unified-authorization-and-elevation.md)
