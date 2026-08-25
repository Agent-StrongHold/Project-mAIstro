---
id: SPEC-252
title: "Tool reversibility taxonomy — registration validation and compensator contract (ADR-050)"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-038
implements:
  - maistro-engine#ADR-050
related:
  - maistro-engine#ADR-051
  - maistro-engine#ADR-056
  - maistro-engine#ADR-068
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/tools/test_reversibility.py
layer: Tools
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-252: Tool reversibility taxonomy — registration validation and compensator contract

> **Convergence note (2026-08-19).** This spec is marked `Implemented` over
> code with no path from any process entry point — see
> [#363](https://github.com/Agent-StrongHold/maistro-engine/issues/363). It
> tracks ADR-050, whose status is knowingly held pending the
> boundary-enforcement ADR.
>
> The status is left unchanged because the spec lifecycle has no way to
> express this. From `Implemented` a spec may only become `Superseded`, which
> requires a `superseded-by`, and no successor document exists. There is no
> `Deprecated` state for specs as there is for ADRs. Correcting this needs
> either the successor spec or a lifecycle change, so the note carries the
> truth in the meantime.


## Context

ADR-050 requires every registered tool to carry a `ToolReversibility` tag (`internal`,
`reversible`, `irreversible`) so substrate can decide retry/escalation/rollback behavior.
Nothing implementing this exists today — `maistro/tools/` has no reversibility concept, and
`security/sentinel` has no `reversibility_of()`/`compensator_for()` surface. This SPEC scopes the
load-bearing validation core: the `ToolReversibility` enum, `ToolRegistration` type, and the
registration-time rules ADR-050 mandates (compensator required for `reversible`, compensator
itself must not be `irreversible`, unknown/untagged external tools default to `irreversible`).

## Goals

- Add `maistro/tools/reversibility.py`: `ToolReversibility` (`StrEnum`: `INTERNAL`, `REVERSIBLE`,
  `IRREVERSIBLE`), `ToolRegistration` (frozen dataclass: `name: str`,
  `reversibility: ToolReversibility`, `compensator: str | None = None`,
  `impact_estimator: str | None = None`, `idempotency_key: str | None = None`),
  `ToolRegistrationError(Exception)`.
- Add `maistro/tools/reversibility_registry.py`: `ReversibilityRegistry` —
  `register(registration: ToolRegistration, *, compensator_reversibility: ToolReversibility |
  None = None) -> None`, `reversibility_of(name: str) -> ToolReversibility`,
  `compensator_for(name: str) -> str | None`. Unregistered tool name raises `KeyError` (no
  silent default at lookup time — only `default_for_external()` below produces the "untagged
  external tool" default, kept as an explicit caller decision, not a registry fallback).
  - `register()` raises `ToolRegistrationError` if `reversibility == REVERSIBLE` and
    `compensator is None`.
  - `register()` raises `ToolRegistrationError` if `reversibility == REVERSIBLE` and the
    caller-supplied `compensator_reversibility == ToolReversibility.IRREVERSIBLE` (the registry
    itself holds only tool registrations, not a second lookup table of compensator tags in this
    SPEC's scope — callers resolve the compensator's own tag and pass it in; see Non-goals).
- Add `default_for_external() -> ToolReversibility` returning `ToolReversibility.IRREVERSIBLE` —
  the one-line policy ADR-050 calls "safe by default" for untagged external MCP tools, kept as a
  named function rather than a magic literal so call sites are self-documenting.
- `ToolRegistration` is the structural artifact `SentinelPolicy.reversibility_of`/
  `compensator_for` (ADR-050's sketch) will eventually proxy to; this SPEC builds the registry
  those methods delegate to, not the `Sentinel` integration itself (see Non-goals).

## Non-goals

- Wiring into `security/sentinel/` (`SentinelPolicy.reversibility_of`/`compensator_for`) —
  follow-up once a real `Sentinel` call site needs this; this SPEC delivers the registry standalone.
- MCP gateway / in-process tool registration call sites actually invoking `register()` — follow-up
  integration PR per tool surface (MCP gateway, in-process, A2A).
- Resolving a compensator's own reversibility by looking it up in the same registry
  (`compensator_reversibility` is caller-supplied here) — once compensators are themselves
  registered tools, `register()` can resolve this internally; deferred until that's true.
  Note compensators must be registered as `internal` or `reversible` tools per ADR-050 — this
  is enforced wherever the compensator's *own* registration happens, not duplicated here.
- Hypothesis state-machine property test that `apply(tool_call); apply(compensator)` restores
  observable state — that test needs real tool/compensator implementations to apply against;
  this SPEC has no such implementations yet (out of scope per ADR-050's own "out of scope"
  section — compensator function bodies are consumer-authored).
- `tool.compensator_invoked` event and `maistro_tool_reversibility_count` metric (ADR-037
  wiring) — follow-up once an event bus call site exists for tool dispatch.
- Code-registry-backed `compensator`/`impact_estimator` refs with microVM execution (ADR-069) —
  these fields are opaque strings here; resolving/executing them is ADR-069's scope.

## Decision

```python
# maistro/tools/reversibility.py
class ToolReversibility(StrEnum):
    INTERNAL = "internal"
    REVERSIBLE = "reversible"
    IRREVERSIBLE = "irreversible"

@dataclass(frozen=True)
class ToolRegistration:
    name: str
    reversibility: ToolReversibility
    compensator: str | None = None
    impact_estimator: str | None = None
    idempotency_key: str | None = None

class ToolRegistrationError(Exception): ...

def default_for_external() -> ToolReversibility:
    return ToolReversibility.IRREVERSIBLE

# maistro/tools/reversibility_registry.py
class ReversibilityRegistry:
    def register(
        self,
        registration: ToolRegistration,
        *,
        compensator_reversibility: ToolReversibility | None = None,
    ) -> None: ...
    def reversibility_of(self, name: str) -> ToolReversibility: ...
    def compensator_for(self, name: str) -> str | None: ...
```

## Acceptance criteria

- [x] Registering an `INTERNAL` or `IRREVERSIBLE` tool with no compensator succeeds.
- [x] Registering a `REVERSIBLE` tool with `compensator=None` raises `ToolRegistrationError`.
- [x] Registering a `REVERSIBLE` tool with a compensator whose
      `compensator_reversibility=IRREVERSIBLE` raises `ToolRegistrationError`.
- [x] Registering a `REVERSIBLE` tool with a valid (`INTERNAL`/`REVERSIBLE`) compensator
      succeeds; `compensator_for()` returns the registered ref.
- [x] `reversibility_of()`/`compensator_for()` on an unregistered name raise `KeyError`.
- [x] `default_for_external()` returns `ToolReversibility.IRREVERSIBLE`.
- [x] Re-registering the same tool name overwrites the prior registration (last write wins, no
      duplicate-registration error — registries in this codebase already follow this convention,
      e.g. `ChannelRegistry` in SPEC-251).

## Testing

- `packages/maistro-core/tests/tools/test_reversibility.py` (new) — registration validation
  matrix above, `KeyError` on unknown tool, `default_for_external()` regression guard.

## Open questions

- Whether `compensator_reversibility` should become a self-resolved lookup once compensators are
  registered as tools in the same registry — deferred per Non-goals; the caller-supplied
  parameter is sufficient for this SPEC's scope and call sites can be simplified later without
  changing `ToolRegistration`'s shape.

## References

- [ADR-050: Tool reversibility taxonomy and compensator contract](../adr/ADR-050-tool-reversibility-taxonomy.md)
- [ADR-051: Tool approval gates](../adr/ADR-051-tool-approval-gates.md)
- `packages/maistro-core/src/maistro/resilience/` (ADR-038 reliability primitives)
