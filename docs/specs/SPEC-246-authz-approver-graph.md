---
id: SPEC-246
title: "Approver graph — declarative policy-matrix resolution (ADR-068 §C)"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-06-20
substrate:
  - maistro-engine#ADR-028
implements:
  - maistro-engine#ADR-068
related:
  - maistro-engine#SPEC-245
  - maistro-engine#SPEC-247
supersedes: []
blocks: []
blocked-by:
  - maistro-engine#SPEC-245
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/security/test_approver_graph.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-246: Approver graph — declarative policy-matrix resolution

## Context

ADR-068 §C requires that "who may satisfy a `delegated-approval`" be a configurable
relational binding (`for-scope` → `approved-by`), not a fixed admin-only tree — e.g.
"team-1 approves team-2," manager→employee, parent→child. SPEC-245 added `AuthzDecision
.approver_scope` as a field but left it `None`; this SPEC resolves it.

## Goals

- Add `ApproverBinding` (action, for-scope, approved-by) and `ApproverGraph` (ordered list
  of bindings + most-specific-match resolution) to `maistro/security/sentinel/`.
- `ApproverGraph.resolve(action, requester_scope) -> str` returns the `approved-by` scope
  string of the most-specific matching binding, or `"role:admin"` if none match (admin is
  always an implicit root approver per ADR-068 §C).
- Wire `ApproverGraph` into `Sentinel.authorize()` (SPEC-245): when the resolved tier is
  `DELEGATED`, populate `AuthzDecision.approver_scope` from `ApproverGraph.resolve(...)`.
- `ApproverGraph.members(scope: str) -> set[str]` resolves a scope string (`team:1`,
  `role:manager`) to the set of principal IDs currently in it, reusing
  `maistro.memory.scopes` scope-matching helpers where the scope axis overlaps.

## Non-goals

- The actual signing/approval UX (who gets notified, how they sign) — that's SPEC-247
  (elevation flows) and ADR-051 (notification channel, explicitly out of scope there too).
- Persisting the policy matrix in a DB-backed config store — ADR-078 / ADR-073 follow-up;
  this SPEC's `ApproverGraph` is constructed from an in-memory list of bindings, injected.

## Decision

```python
@dataclass(frozen=True)
class ApproverBinding:
    action: str          # action name or reversibility/impact class
    for_scope: str        # e.g. "team:2", "user:*"
    approved_by: str      # e.g. "team:1", "role:manager"

class ApproverGraph:
    def __init__(self, bindings: list[ApproverBinding]) -> None: ...

    def resolve(self, action: str, requester_scope: str) -> str:
        """Most-specific (action, for_scope) match's approved_by; "role:admin" if none."""

    def members(self, scope: str) -> set[str]:
        """Resolve a scope string to current principal IDs (delegates to
        maistro.memory.scopes for team:/org:/user: prefixes; role: prefixes
        resolve against Principal.roles)."""
```

Specificity ordering for `resolve`: exact `(action, for_scope)` match > exact-action
wildcard-scope (`for_scope="*"` or `"user:*"`) > no match (falls to `"role:admin"`).
Self-elevation is the degenerate case where `approved_by == for_scope` (the principal
approves themselves) — `ApproverGraph` does not special-case this; SPEC-245's tier
resolution already routes self-elevation-tier actions away from `ApproverGraph.resolve`.

## Acceptance criteria

- [ ] `resolve()` picks the most-specific binding for `(action, requester_scope)`; falls
      back to `"role:admin"` when no binding matches.
- [ ] Two users in `team:1` running action `X` resolve to `role_team_auto` (SPEC-245), never
      reaching `ApproverGraph.resolve` at all; two users in `team:2` running the same action
      with a `team:2 → team:1` binding get `approver_scope == "team:1"`.
- [ ] `members("role:manager")` and `members("team:1")` both return non-empty sets given
      seeded principals; an unknown scope string returns an empty set (not an error).
- [ ] Admin is always resolvable as an approver even with zero matching bindings.

## Testing

- `packages/maistro-core/tests/security/test_approver_graph.py` (new) — binding specificity
  resolution, the manager→employee / parent→child / team→team examples from ADR-068 §C,
  `members()` resolution for `team:`/`role:` scope prefixes, admin-fallback.

## Open questions

- Whether `members()` needs an injected `PrincipalStore` lookup or can resolve purely from
  `Principal.scopes`/`roles` passed at call time — deferred to implementation; likely the
  latter for this SPEC's static-graph scope, revisited if a DB-backed principal directory
  lands first.

## References

- `packages/maistro-core/src/maistro/memory/scopes.py`
- [ADR-068: Unified Authorization & Elevation](../adr/ADR-068-unified-authorization-and-elevation.md)
- [SPEC-245: Authorization tier ladder](SPEC-245-authz-tier-ladder.md)
