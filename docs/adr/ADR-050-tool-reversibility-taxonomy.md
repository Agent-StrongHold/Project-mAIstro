---
id: ADR-050
title: Tool reversibility taxonomy and compensator contract
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-13
substrate:
  - maistro-engine#ADR-038
implements: []
related:
  - maistro-engine#ADR-051
  - maistro-engine#ADR-055
  - maistro-engine#ADR-056
  - maistro-engine#ADR-068
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Tools
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-13
  - status: Implemented
---

# ADR-050: Tool reversibility taxonomy and compensator contract

> **Convergence note (2026-08-19).** This ADR is marked `Implemented` over
> code with no path from any process entry point — see
> [#363](https://github.com/Agent-StrongHold/maistro-engine/issues/363). The
> status is knowingly left unchanged rather than corrected, because neither
> available transition is right yet. Tool reversibility belongs on the Binding
> → Invocation path.
>
> The capability is still wanted, so `Deprecated` would be false. `Superseded`
> is the right eventual transition — the boundary that replaces this is
> specified by
> [ADR-081226-6b46](ADR-081226-6b46-capability-provider-binding-invocation.md),
> which puts policy narrowing on the Binding and records policy decisions on
> the Invocation — but that ADR does not specify the durable approval
> mechanism that actually shipped across
> [#430](https://github.com/Agent-StrongHold/maistro-engine/pull/430) through
> [#433](https://github.com/Agent-StrongHold/maistro-engine/pull/433) and
> [#467](https://github.com/Agent-StrongHold/maistro-engine/pull/467), and
> [SPEC-081226-6e34](../specs/SPEC-081226-6e34-hierarchical-permissions.md)
> explicitly puts approval out of scope. Pointing `superseded-by` at an ADR
> that does not cover the replacing mechanism would repeat the fabrication
> this correction exists to remove. Both target states are terminal, so the
> supersession waits for an ADR that genuinely covers it.


## Context

`security/sentinel` enforces tool-call policy today; ADR-038 ships retry / circuit-breaker / fallback / idempotency-key contract. Neither classifies tool calls by side-effect nature. Without a taxonomy, every tool's failure-mode and rollback story is bespoke and substrate cannot reason about which calls are safe to retry, which need approval (ADR-051), and which need a compensator on rollback.

Hermes-desktop ships a coarse reversibility distinction inline in its agent loop — internal scratch operations run autonomously, outbound effects prompt. Lifting that distinction to a substrate-level tag makes it composable with Sentinel policy, ADR-038 reliability primitives, and ADR-051 approval gates.

## Problem

No substrate classification of tool side-effects. Reversibility, compensator availability, and impact-of-failure are implicit per tool, so substrate cannot make safe choices about retry, escalation, or rollback.

## Decision

Three-tier reversibility tag on every registered tool:

| Tier | Meaning | Substrate behaviour |
|---|---|---|
| `internal` | No external side effect. Safe to re-issue freely. | Free retry; no approval gate. |
| `reversible` | External side effect with a paired compensator that restores observable state. | Free retry under ADR-038 idempotency contract; rollback via compensator on task failure. |
| `irreversible` | External side effect that cannot be cleanly undone (money, public posts, mass actions). | Approval gate per ADR-051; recovery via ADR-056 layered contract. |

Reversible tools register a `compensator` (a code-registry ref) that is itself `internal` or `reversible` — never `irreversible`. Substrate refuses to register a `reversible` tool without a compensator.

Irreversible tools register an `impact_estimator` (code-registry ref) for ADR-051 to weight the approval UI, and ideally an `idempotency_key` builder per ADR-038. External MCP tools that declare neither default to `irreversible` with no estimator — safe by default; explicit downgrade requires a Sentinel policy.

> **Result caching (amended 2026-05-30).** A tool may additionally declare itself `deterministic`;
> only then are its results memoised, keyed by `(tool, args, version)` with a TTL. Non-deterministic
> tools, `reversible` tools with observable side-effects, and `irreversible` tools are **never**
> cached (a cached side-effecting call would silently skip the effect). Determinism is opt-in and
> explicit; the safe default is no caching.

## Interface (sketch)

```python
class ToolReversibility(StrEnum):
    INTERNAL = "internal"
    REVERSIBLE = "reversible"
    IRREVERSIBLE = "irreversible"

class ToolRegistration(BaseModel):
    name: str
    reversibility: ToolReversibility
    compensator: str | None = None        # code-registry ref, REQUIRED if reversibility == REVERSIBLE
    impact_estimator: str | None = None   # code-registry ref, RECOMMENDED if IRREVERSIBLE
    idempotency_key: str | None = None    # code-registry ref, RECOMMENDED if IRREVERSIBLE
```

Sentinel exposes:

```python
class SentinelPolicy(Protocol):
    def reversibility_of(self, tool_call: ToolCall) -> ToolReversibility: ...
    def compensator_for(self, tool_call: ToolCall) -> str | None: ...
```

## Acceptance criteria

- [ ] Every tool registered (via MCP gateway, in-process, or A2A) carries a `reversibility` tag.
- [ ] Registering a `REVERSIBLE` tool without a compensator fails at registration with `ToolRegistrationError`.
- [ ] Registering a tool whose declared compensator is itself `IRREVERSIBLE` fails at registration.
- [ ] External MCP tools without an explicit tag default to `IRREVERSIBLE`.
- [ ] Hypothesis property test: for any `(tool_call, compensator)` pair declared reversible, `apply(tool_call); apply(compensator)` restores observable state (state-machine model).
- [ ] Event `tool.compensator_invoked{tool, outcome}` per ADR-037.
- [ ] Metric `maistro_tool_reversibility_count{reversibility}` per ADR-037.

## Open questions

1. **Single code registry shared with recipe-overlay refs (ADR-053)?** **Resolved by ADR-069:
   yes** — one registry for impact estimators, compensators, merge resolvers, and dynamic gates,
   with microVM-isolated execution under the ADR-068 authorization envelope.
2. **Default for external MCP tools.** Recommend `IRREVERSIBLE` (safe) with explicit Sentinel policy override. Stronger option: refuse to register without a tag.
3. **Partial failure inside a compensator.** Recommend explicit: compensator failures bubble as `CompensatorError` and escalate via ADR-051 bubble-up path ("compensator failed; what now?").
4. **Tag inheritance for tools-as-agents (A2A delegation).** Recommend the delegate carries the strictest tag of its callable tools — propagate up.

## Source references

- `maistro-engine:src/maistro/security/sentinel/`
- `maistro-engine:src/maistro/tools/` (in-process + MCP gateway)
- ADR-038 idempotency-key requirement for non-idempotent ops.

## Out of scope

- The compensator function bodies (consumer-authored).
- Multi-step saga orchestration (separate ADR if needed).
- Cross-tenant compensator trust (stronghold concern).
