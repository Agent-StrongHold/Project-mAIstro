---
id: ADR-058
title: Agent-to-agent (A2A) delegation protocol — in-process and federated
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-05-29
substrate:
  - maistro-engine#ADR-004
  - maistro-engine#ADR-024
  - maistro-engine#ADR-038
implements: []
related:
  - maistro-engine#ADR-019
  - maistro-engine#ADR-037
  - maistro-engine#ADR-052
  - maistro-engine#SPEC-008
  - maistro-engine#SPEC-019
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-29
---

# ADR-058: Agent-to-agent (A2A) delegation protocol — in-process and federated

## Context

`maistro.a2a` ships today as **dead scaffold**: `a2a/__init__.py` is empty (nothing is exported), and three modules sit unwired:

- `delegate.py` — `A2ADelegator`, `A2ATask`, `DelegationMode {NONE, ALLOW_ALL, ALLOW_LIST}`, `TaskStatus`. Creates/queues task records in an in-memory dict; capability registry maps `agent → can_delegate_to[]`.
- `lifecycle.py` — `TaskQueue` (priority P0–P5), `WorkerPool` (timeout/retry), `TaskLifecycleManager`. `_execute_task` is a `sleep(0.1)` stub; `TaskQueue.enqueue` generates a `task_id` it never stores on the task.
- `guest_peers.py` — `GuestPeerManager`, `PeerTrust`, `DelegationResult`. POSTs to a peer's `/a2a/tasks/create` with a `Bearer` credential — but `peer_url` is unvalidated (**SSRF**; the medium finding in the May review).

Meanwhile the *intent* to delegate already exists on the request path but dead-ends:

- `types/agent.py` `ReasoningResult.delegate_to` / `delegate_message`.
- `agents/strategies/delegate.py` `DelegateStrategy` (task-type → agent-name router); registered by `agents/factory.py`.
- `agents/catalog.py` `AgentCard.delegation_mode` + `sub_agents`; set by `agents/pm_fleet.py`.
- `agents/base.py` `Agent.handle()` **ignores** `delegate_to`/`done=False` (the "delegation is dead end-to-end" high finding; **fixed on `fix/agents-delegation`, PR #39**).

Prior art constrains the design: **SPEC-008** (direct A2A RPC with depth/latency/token budgets, capability envelope, circular-delegation prevention, audit VC), **ADR-024** (DID/VC for federation trust), **ADR-038** (per-A2A-peer circuit breaker), **ADR-037** (`agent.delegate` observability event), **ADR-052** (parallel agent waves). **ADR-019** governance: this is shared runtime in maistro-core, product-agnostic, **no `org_id`**.

## Problem

There is no path from "an agent decides to delegate" to "a sub-agent (local) or peer (remote) actually runs the work and returns a result." The pieces exist but are not a protocol: no public API surface, no execution bridge, no budgets/loop-guards, no safe egress, no audit. Two distinct delegation kinds are conflated:

1. **In-process delegation** — Agent A hands a sub-task to Agent B *in the same runtime* (the PM-fleet / `sub_agents` case). Synchronous, cheap, no network.
2. **Federated delegation** — Agent A delegates to a *remote* peer Conductor over HTTP (the `guest_peers` case). Untrusted boundary, needs egress allow-listing, mutual identity, and reliability policy.

## Decision

Define **one A2A protocol with two transports** behind a single `A2ABroker` facade, exported from `a2a/__init__.py`.

### 1. Public surface (`a2a/__init__.py` exports)

`A2ABroker`, `A2ATask`, `TaskStatus`, `DelegationMode`, `DelegationBudget`, `DelegationResult`, `PeerTrust`, `LocalTransport`, `FederatedTransport`, `A2AError` (+ subclasses).

### 2. Execution bridge (closes the dead-end)

`Agent.handle()` (post-PR #39) detects `ReasoningResult.delegate_to` and calls `A2ABroker.delegate(...)` instead of returning empty content. The broker resolves the target:

- target is a **local** `AgentCard` id → `LocalTransport` (invoke via the existing agent factory/conduit), subject to the caller's `AgentCard.delegation_mode` + `sub_agents` allow-list.
- target is a **registered peer** name → `FederatedTransport` (`GuestPeerManager`), subject to `PeerTrust.allowed_agents`.

### 3. Capability envelope + loop guard (SPEC-008)

Every delegation carries a `DelegationBudget` that decrements across hops:

```python
@dataclass(frozen=True)
class DelegationBudget:
    max_depth: int = 3            # hops remaining; 0 ⇒ refuse to delegate further
    deadline: datetime            # absolute latency budget (wall clock)
    token_budget: int             # shared LLM token ceiling across the sub-tree
    trace_id: str                 # correlates the whole delegation tree
    chain: tuple[str, ...] = ()   # agent/peer ids already in the path (cycle guard)
```

`A2ABroker.delegate` refuses (raises `DelegationRefused`) when `max_depth == 0`, the deadline has passed, the budget is exhausted, or the target is already in `chain` (circular-delegation prevention). Each hop appends its id to `chain` and decrements `max_depth`.

### 4. Federated transport hardening

- **Egress allow-list (fixes the SSRF):** `peer_url` must be `https://` (or explicitly-allowed `http://` for a configured dev peer), and the resolved IP must not be loopback/link-local/private/reserved (block `127.0.0.0/8`, `169.254.0.0/16`, `::1`, `fc00::/7`, `fe80::/10`, RFC-1918) unless that peer is explicitly marked `trust_local=True`. Validation lives in `PeerTrust` construction and is re-checked at call time (DNS-rebind guard).
- **Mutual identity (ADR-024):** outbound requests are signed with the Conductor DID; peers are pinned by DID, not bare URL. The `Bearer` credential is sent **only** after egress + identity checks pass.
- **Reliability (ADR-038):** each peer gets its own circuit breaker + retry policy from the resilience taxonomy; the per-attempt single POST is replaced by the standard retry/backoff path.

### 5. Lifecycle fixes

- `TaskQueue.enqueue` stores the generated `task_id` **on** the task record (`task["id"] = task_id`) so dequeue correlates.
- `WorkerPool._execute_task` invokes the real local agent (in-process) rather than sleeping.
- `delegate.py` log args corrected (`task_id, from_agent, to_agent`).

### 6. Observability + audit

Emit `agent.delegate.requested|completed|refused|failed` (ADR-037) with `{trace_id, from, to, transport, depth}`; for federated hops, record a signed delegation VC in the audit log (ADR-024, SPEC-019). No `org_id` on any event (ADR-019).

## Interface (sketch)

```python
class A2ABroker:
    def __init__(self, *, local: LocalTransport, federated: FederatedTransport,
                 audit: AuditLogger) -> None: ...

    async def delegate(
        self,
        *,
        from_agent: str,
        to: str,                       # local AgentCard id OR registered peer name
        task: str,
        budget: DelegationBudget,
        mode: DelegationMode = DelegationMode.ALLOW_LIST,
    ) -> DelegationResult: ...

class Transport(Protocol):
    async def run(self, task: A2ATask, budget: DelegationBudget) -> DelegationResult: ...
```

## Acceptance criteria

- [ ] `a2a/__init__.py` exports the public surface; `from maistro.a2a import A2ABroker` works.
- [ ] An agent with `reasoning.strategy='delegate'` and a `sub_agents` allow-list delegates **in-process** and returns the sub-agent's non-empty response (builds on PR #39).
- [ ] Delegating to an id **not** in `sub_agents`/`allowed_agents` raises `DelegationRefused`.
- [ ] `max_depth=0`, a passed `deadline`, an exhausted `token_budget`, or a target already in `chain` each cause `DelegationRefused` (no infinite/again-delegation).
- [ ] `FederatedTransport` rejects a `peer_url` resolving to loopback/private/link-local/reserved IP, and rejects non-`https` peers unless explicitly allowed — **no Bearer credential is sent** on rejection. (SSRF regression test.)
- [ ] Federated delegation goes through the ADR-038 per-peer circuit breaker + retry, not a bare single POST.
- [ ] `TaskQueue.enqueue` round-trips: the returned `task_id` is retrievable from the dequeued task.
- [ ] `agent.delegate.*` events emitted; federated hops produce a signed audit VC; no event carries `org_id`.
- [ ] Hypothesis property test: for any delegation tree, depth never exceeds `max_depth` and no agent id appears twice in any root-to-leaf path.

## Resolved decisions (v0)

1. **Result model → sync await with a deadline (v0).** In-process delegation awaits the sub-agent; federated awaits the peer — both bounded by a deadline (matches the SPEC-008 latency budget). Async fire-and-poll (`TaskQueue`/`WorkerPool`) is an **async-batch follow-up**, not v0.
2. **`TaskLifecycleManager`/`WorkerPool` → not in v0.** The broker + two transports + budgets are the MVP; the worker pool is marked **explicitly experimental** rather than shipped as a sleeping stub.
3. **Trust tiers for local delegation → enforce `target.trust_tier ≤ caller.trust_tier`.** Unless the caller's `sub_agents` explicitly lists the target (SPEC-012 privilege separation; consistent with the ADR-068 rule that an agent holds a subset of its caller's authority).
4. **Peer identity → DID-pin when available.** Pin peers by DID (ADR-024) when the peer publishes `did:web`; URL+key fallback otherwise; a config flag can require DID.
5. **Token-budget across transports → real local, advisory federated.** Local hops read real usage once graph token accounting lands; federated hops treat the peer's reported usage as **advisory** and additionally enforce the wall-clock `deadline`.

## Source references

- `maistro-engine:packages/maistro-core/src/maistro/a2a/{delegate,lifecycle,guest_peers}.py` — existing scaffold + defects.
- `maistro-engine:packages/maistro-core/src/maistro/agents/strategies/delegate.py`, `agents/base.py`, `agents/catalog.py`, `agents/pm_fleet.py` — delegation intent + AgentCard fields.
- ADR-004 agent spec / execution envelope.
- ADR-024 DID/VC (federation trust, audit VCs).
- ADR-037 observability taxonomy (`agent.delegate`).
- ADR-038 reliability taxonomy (per-A2A-peer circuit breaker).
- ADR-052 parallel agent waves.
- SPEC-008 agent networking (depth/latency/token budgets, capability envelope, circular-delegation prevention).
- SPEC-019 human-as-node delegation (signed delegation VCs).
- ADR-019 governance — shared runtime, no `org_id`.

## Out of scope

- Async/queued delegation at scale (`WorkerPool` real execution, backpressure) — follow-up once a fan-out workload exists.
- DIDComm v2 / on-chain peer discovery.
- Cross-tenant delegation isolation (Stronghold concern; no `org_id` here).
- Persisting `A2ATask` beyond in-memory (a persistence-layer follow-up; the broker depends on a store protocol so it can be added without API change).
- The SSRF fix as a standalone patch — it is folded into `FederatedTransport` here rather than shipped separately.
