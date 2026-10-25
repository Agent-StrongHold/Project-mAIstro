---
inventory-delta:
  packages/maistro-design/tests: +7
  packages/hive-conductor/backend/tests: +2
---

> **STATUS: SUPERSEDED — provenance only, not current tree state.**
> The DesignEngine WorkspaceAgent/Reconciler injection seam described below
> was added in round 57 (`baee9f5fe`) and **removed** in round 65
> (`f753cfe8e`, "eliminate dead DesignEngine seam surface"): it had zero
> production consumers, tripped the vulture per-identity gate, and the #777
> stop condition forbids reintroducing a Design-Studio-private reconciler.
> The two tests this note claims (`test_engine_workspace_seam.py` and
> `TestTheWorkspaceAgentSeamIsTheRealFrontDoor`) were deleted in round 65 and
> **no longer exist** at HEAD `2d41e05a5` (verified by `ls`/`grep`). Authoritative
> reversal: `777-remove-dead-design-seams.md` (delta −7 / −2). The present-tense
> claims below describe round-57 state, not HEAD.

# DesignEngine #777 injection seams: persistent Workspace Agent front door + canonical reconciler

## What changed and why

Issue #777 requires Design Studio to *consume* the persistent Workspace Agent
(#53) and the canonical execution reconciler instead of instantiating
Design-Studio-private ones. `DesignEngine` (the Design Studio core in
`packages/maistro-design`) cannot depend on the app layer that owns those
objects, so the dependency direction is inverted through constructor injection:

- `WorkspaceAgentResolver` — protocol for the #53 front door. The reference
  Conductor injects `services.workspace_agent.resolve_workspace_agent`
  (`packages/hive-conductor/backend/services/design_service.py`), whose
  contract (one persistent roster row per Workspace; `WorkspaceNotFound` /
  `WorkspaceAgentConflict` ownership errors) the protocol docstring names.
- `ReconcilerFactory` — protocol for the canonical
  `maistro.runs.reconciliation.AttemptLifecycleReconciler` over a
  caller-supplied `RunStore`. This reconciles *physical Attempts into logical
  Run/NodeRun state*; it is deliberately documented as NOT Goal reconciliation
  (#804/#805/#806), which is owned elsewhere and unlanded at this head.

With nothing injected, the accessors raise `RuntimeError` naming the missing
dependency — a missing canonical owner must fail loudly, never silently become
a private substitute (the issue's stop condition).

## Truthfulness repairs applied to the salvaged seam (round 57)

The seam arrived via salvage commit `52bff5022` with three defects, fixed here:

1. `get_reconciler` and the class docstring claimed the reconciler was "for
   Goal reconciliation" — false: `maistro.runs.reconciliation` states it "owns
   universal lifecycle bookkeeping only" and never decides Goal-level
   questions. Docstrings now state exactly what it is and that #804 owns Goal
   reconciliation.
2. The resolver protocol was annotated `-> maistro.agents.base.Agent` (the
   runtime agent-instance class) while the canonical front door returns the
   app layer's persistent roster row (`models.schemas.Agent`). The protocol
   now types the return loosely and names the canonical producer and its error
   types in prose, since this package does not own them.
3. The `# New types for optional dependencies` comment and fabricated framing
   were replaced with a statement of the consume-not-own contract.

## Production wiring

`start_design_service` now injects the real front door:
`workspace_agent_resolver=workspace_agent_service.resolve_workspace_agent`.
The `reconciler_factory` seam stays uninjected in the app: run-store wiring is
owned by `maistro.runs.wiring`, and the Goal reconciler an injection would
actually want (#804) has not landed.

## Tests

- `packages/maistro-design/tests/test_engine_workspace_seam.py` (+7): the
  unconfigured engine refuses (no private agent/reconciler); the injected
  resolver's return passes through untouched; the reference front door shape
  satisfies the runtime-checkable protocol; the factory builds the canonical
  `AttemptLifecycleReconciler` over the caller's store with the event sink
  forwarded; the production factory shape satisfies the protocol.
- `packages/hive-conductor/backend/tests/test_design_service_startup.py`
  (+2, class `TestTheWorkspaceAgentSeamIsTheRealFrontDoor`): the engine built
  by `start_design_service` returns the canonical roster row (identity-equal
  to the front door's own resolution) and raises the front door's
  `WorkspaceNotFound` for an unknown Workspace.
