---
id: SPEC-182
title: A2A delegation broker — implementation
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-05-29
accepted: null
implemented: null
substrate:
  - maistro-engine#ADR-058
implements:
  - maistro-engine#ADR-058
related:
  - maistro-engine#SPEC-008
  - maistro-engine#SPEC-181
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/a2a/test_public_surface.py
  - packages/maistro-core/tests/a2a/test_broker.py
  - packages/maistro-core/tests/a2a/test_budget_properties.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-29
  - status: Accepted
---

# SPEC-182: A2A delegation broker — implementation

Implements [ADR-058](../adr/ADR-058-a2a-delegation-protocol.md). Builds on the delegation execution-bridge fix in PR #39 (`fix/agents-delegation`).

> **Implementation status (2026-07-02):** Phases 1-2 are implemented
> (`a2a/__init__.py` export surface, lifecycle/log/metadata fixes,
> `DelegationBudget` + `A2ABroker` + `LocalTransport` in `a2a/broker.py`,
> tests in `packages/maistro-core/tests/a2a/`). Phase 3 (FederatedTransport,
> SSRF hardening, circuit breaking) and Phase 4 (observability + audit VC)
> are follow-up, as is the `Agent.handle()` → broker wiring (post-PR #39).

## Context

The `maistro.a2a` scaffold exists but is unexported and unwired (empty `__init__.py`), and delegation intent (`ReasoningResult.delegate_to`) dead-ends. ADR-058 defines one protocol with two transports (local, federated) behind an `A2ABroker`, with a `DelegationBudget` loop-guard and SSRF-safe egress.

## Decision (target)

Land in phases; each phase is one PR to `integration` with TDD (RED→GREEN), `ruff`/`mypy --strict` clean on touched files.

### Phase 1 — export surface + lifecycle fixes (no behavior change to callers)
- Populate `a2a/__init__.py` with the ADR-058 public exports.
- Fix `TaskQueue.enqueue` to store `task["id"] = task_id`; fix swapped log args in `delegate.py`; persist/use the `metadata` param or drop it.
- Tests: `enqueue` round-trip; import surface smoke test.

### Phase 2 — `DelegationBudget` + `A2ABroker` + `LocalTransport`
- Add `DelegationBudget` (max_depth, deadline, token_budget, trace_id, chain) and refusal rules (`DelegationRefused`).
- `A2ABroker.delegate` resolves a local `AgentCard` id, enforces `delegation_mode`/`sub_agents` allow-list and `target.trust_tier ≤ caller.trust_tier`, decrements depth, appends to `chain`, invokes the sub-agent via the existing factory/conduit.
- Wire `Agent.handle()` (post-PR #39) to call the broker on `delegate_to`.
- Tests: in-process delegate returns sub-agent response; non-allow-listed target refused; depth/deadline/cycle/budget each refuse; trust-tier escalation refused.

### Phase 3 — `FederatedTransport` (SSRF-safe) + reliability
- Egress allow-list in `PeerTrust` construction **and** at call time (DNS-rebind guard): require `https` (or explicit dev `http`); block loopback/link-local/private/reserved IPs unless `trust_local=True`. No `Authorization` header sent on rejection.
- Route the peer POST through the ADR-038 per-peer circuit breaker + retry (replace the bare single `httpx.post`).
- Sign outbound with the Conductor DID; pin peers by DID when available (ADR-024).
- Tests: SSRF regression (loopback/metadata-IP/non-https rejected, no Bearer leaked); circuit-breaker opens after N failures; happy-path federated delegate returns peer result.

### Phase 4 — observability + audit
- Emit `agent.delegate.requested|completed|refused|failed` (ADR-037); signed delegation VC for federated hops (ADR-024/SPEC-019).
- CI grep: no `org_id` on A2A events/records.

## Out of scope (this spec)
- Async/queued delegation via real `WorkerPool` execution (ADR-058 open question 2) — `WorkerPool` stays marked experimental.
- Persisting `A2ATask` to a database (broker depends on a store protocol so this is additive later).
- Inbound A2A receive endpoint on hive-conductor (`/a2a/tasks/create` handler) — separate hive-conductor spec; this spec covers the **outbound/broker** side in core.

## Test strategy
- Unit + Hypothesis property test (ADR-058): across any generated delegation tree, depth ≤ `max_depth` and no id repeats on any root-to-leaf path.
- Run: `PYTHONPATH=packages/maistro-core/src python -m pytest packages/maistro-core/tests/a2a -q`.

## References
- [ADR-058](../adr/ADR-058-a2a-delegation-protocol.md)
- [SPEC-008](SPEC-008-agent-networking.md)
- PR #39 `fix/agents-delegation` (handle() honors `delegate_to`).
