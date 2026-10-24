---
id: SPEC-188
title: "Self-repair — autonomous detect→diagnose→propose→act remediation loop over infra_monitor/infra_action/approval"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-05-30
substrate:
  - maistro-engine#ADR-031
  - maistro-engine#ADR-038
implements: []
related:
  - maistro-engine#SPEC-184
  - maistro-engine#SPEC-187
  - maistro-engine#SPEC-011
supersedes: []
blocks: []
blocked-by:
  - maistro-engine#SPEC-184
  - maistro-engine#SPEC-187
contracts:
  - boundary
  - behavioral
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-30
---

# SPEC-188: Self-Repair Loop

## Context

The migration goal is for mAIstro to **run, repair, and monitor** the server — not just observe it.
SPEC-187 delivered the primitives: `infra_monitor` (normalized `InfraHealth`), `infra_action`
(allowlisted, blast-radius-tiered host actions), and the `approval` gate. Phase 1b (capability
wiring) put those in the `Container`'s `CapabilityRegistry` and exposed them over `/v1/capabilities`.

`self_repair` is the **net-new headline loop** — decomposition item #4 of SPEC-184. It closes the
control loop: observe health → diagnose a likely root cause → propose a remediation → act through
`infra_action` (which auto-runs safe fixes and routes risky ones through `approval`). It is the
piece that makes "mAIstro repairs the server" true rather than aspirational.

It is **composition, not new privilege**: self_repair invents no host access. It reads through
`infra_monitor` and acts only through `infra_action`, so every safety property SPEC-187 established
(server-side allowlist, VMID allowlist, tiered autonomy, approval gate, audit) holds unchanged. What
self_repair adds is the *decision* layer — which action, when, how often, and when to stop and ask a
human — plus the *safety* layer that keeps an autonomous actuator from making things worse.

## Goals

1. A `self_repair` slot whose provider runs a bounded **detect → diagnose → propose → act** cycle.
2. **Detect** degraded/down resources from `infra_monitor` snapshots.
3. **Diagnose** a symptom → a candidate remediation via an explicit, auditable rule table (not an
   opaque model call) — with an optional LLM-assisted explanation that never widens the action set.
4. **Propose** a remediation plan (`{resource, symptom, action, params, tier, rationale}`) that is
   the unit of record, whether or not it auto-executes.
5. **Act** through `infra_action` only — safe fixes auto-run, risky fixes consult `approval`.
6. **Never make it worse:** per-resource attempt budgets, cooldowns, exponential backoff, flap
   detection, and a global kill-switch. An autonomous loop that can restart things MUST be
   self-limiting.

## Non-goals

- Re-implementing host access or widening the `infra_action` allowlist (SPEC-187 owns that boundary).
- Predictive/ML anomaly detection. v1 diagnosis is a deterministic rule table; LLM is explanation-only.
- Smart-home remediation (HA scenes/devices) — a later slot; this loop targets server infra.
- Multi-host orchestration. One host-health API surface (`:8150`) for v1.
- Replacing human operators for `destructive` fixes — those always route through `approval`.

## Decision

### `self_repair` slot

Fallback policy `safe_noop` (SPEC-184): with no active provider, or when `infra_monitor` is
unavailable, the slot returns a typed "self-repair unavailable" and never throws into a caller. The
baseline-eligible core provider is `rule_based_repair`; enhanced providers (e.g. an LLM-planner
variant) can fill the same slot later without changing callers.

Slot protocol (`SelfRepair`, extends `CapabilityProvider`):

```python
@runtime_checkable
class SelfRepair(CapabilityProvider, Protocol):
    async def evaluate(self, health: InfraHealth) -> list[RepairProposal]: ...   # detect + diagnose + propose
    async def run_once(self) -> RepairCycleResult: ...                            # full cycle: snapshot → evaluate → act
```

`run_once()` is the unit a scheduler/operator invokes; `evaluate()` is the pure, testable
detect+diagnose+propose step (no side effects), so diagnosis can be unit-tested without acting.

### The cycle

```
run_once()
  1. DETECT   health = infra_monitor.snapshot()          # SAFE_NOOP if monitor down → empty cycle
              degraded = [r for r in health.resources if r.status in {degraded, down}]
  2. DIAGNOSE for each degraded resource: rule table → candidate RepairProposal (or "no known fix")
  3. PROPOSE  filter through the safety governor (budget/cooldown/flap/kill-switch) → actionable set
  4. ACT      for each actionable proposal: infra_action.act(action, params)
                 → auto-runs (read/reversible+auto_safe) or returns blocked_pending_approval
              record outcome; update per-resource attempt state; emit events + audit
```

With `infra_action.autonomy = detect_only`, step 4 records proposals but dispatches nothing
(monitor-and-advise mode). `auto_safe` (default) auto-runs safe tiers and approval-gates the rest.
`approve_all` routes everything through `approval`.

### Diagnosis — explicit rule table (v1)

Symptom → candidate remediation is a static, auditable table. The action is always one already on
SPEC-187's allowlist; self_repair never synthesizes new actions. The table reads the **normalized**
snapshot the `infra_monitor` provider emits (an anti-corruption layer over the host-health API's raw
`/full` shapes), and the policy is grounded in the **host API's own classification** of container
state — which already distinguishes a fixable container from a crash-loop from an intentional stop.

| Resource | Normalized signal | Candidate action | Tier | Notes |
|---|---|---|---|---|
| `docker` | container `state=unhealthy` (Up, healthcheck failing) | `restart_container{name}` | reversible | the only docker auto-fix |
| `docker` | container `state=restarting` (crash-loop) | **no auto-action** → propose-only | n/a | "needs a human, not another kick" |
| `docker` | container `state=stopped` (Exited/Dead) | **ignored** — no proposal | n/a | intentional absence, not in scope |
| `services` | systemd unit `status=failed` | `restart_service{name}` | reversible | |
| `storage` | ZFS pool not healthy | **no auto-action** → propose-only | n/a | data risk → human review |
| `vms` / `gpu` | — | **observed only** | n/a | no expected-state signal in `/full`; not auto-remediated in v1 |
| any | section degraded/down, no recognized cause | no proposal; record `undiagnosed` | n/a | fail safe to escalation |

**Realism note (vs. the original draft):** the live `/full` carries per-container health buckets
(`unhealthy`/`restarting`/`stopped`), systemd unit states, and a `zpool` string — but **no**
compose-project "stack" status, no "model-server-reachable" signal in the `gpu` section, and no
expected-state for VMs. So v1 auto-remediation is realistically just `restart_container` (unhealthy)
and `restart_service` (failed) — both **reversible**. `restart_stack`/`docker_prune`/`vm_control`
remain operator-initiated; self_repair does not auto-propose destructive actions from health signals.
The approval path is still exercised under `autonomy=approve_all` (where even reversible fixes gate).

Unknown or ambiguous symptoms produce **no action** — fail safe to escalation, never guess. Storage
degradation (data risk) and crash-loops are deliberately propose-only. An optional LLM step may attach
a human-readable `rationale` to a proposal but **cannot change the action or its tier**.

### Safety governor — "never make it worse"

An autonomous actuator that restarts infrastructure must be aggressively self-limiting. Before any
proposal becomes actionable it passes the governor:

- **Per-resource attempt budget.** At most *N* remediation attempts per resource per rolling window
  (default 3 / 30 min). Exhausted → stop acting, escalate to human via `approval`/event.
- **Cooldown + backoff.** After acting on a resource, a cooldown before re-acting on it; repeated
  failures back off exponentially (reuse `maistro.resilience` backoff/jitter, ADR-038).
- **Flap detection.** If a resource recovers then re-fails repeatedly (oscillation), stop
  auto-remediating it and escalate — a restart loop is worse than a clean outage.
- **Idempotent in-flight guard.** Never issue a second action for a resource while one is pending
  approval or executing.
- **Global kill-switch.** A single setting (`self_repair.enabled=false` or autonomy `detect_only`)
  halts all action immediately; the slot disable path (SPEC-184) is the hard stop.
- **No cascading fixes in one cycle.** Cap actions per `run_once()` (default 1–2) so a bad snapshot
  can't trigger a storm; remaining proposals wait for the next cycle's fresh health read.

All governor decisions (acted / suppressed-by-budget / cooldown / flap / escalated) are events +
audit entries, so the loop's behavior is fully reconstructable after the fact.

### Trigger / cadence

`run_once()` is invoked by the existing scheduler (`maistro.scheduling`) on a cadence (default
60–120 s) and on-demand via the API. v1 does not add a bespoke daemon; it rides the scheduler so it
inherits start/stop, and the same UI-parity rule applies — see below. Cadence and budgets are
settings, not constants.

### Surface (UI parity)

Per the platform's UI-parity rule, every self_repair operation is an API call first; the web UI,
`maistro` CLI, and any TUI are clients:

- `GET  /v1/capabilities/self-repair/proposals` — current/recent proposals + governor state.
- `POST /v1/capabilities/self-repair/run` — trigger one cycle now (gated `config.write`).
- `PATCH /v1/capabilities/self_repair` — enable/disable + set autonomy (existing capability PATCH).
- Risky remediations surface in the **same approval inbox** as SPEC-187 (`/v1/capabilities/approvals`,
  `maistro approvals …`) — self_repair is just another `requester`.

### Security boundary

- self_repair holds **no** host privilege; it can only dispatch what `infra_action` already permits,
  so the server-side allowlist/VMID/path guards remain the authority (defense-in-depth).
- Every proposal, suppression, and executed/denied action is audit-logged with
  `{resource, symptom, action, params, tier, decision, actor/requester, outcome}`.
- `destructive` remediations **always** route through `approval`; self_repair cannot bypass the gate.

## Acceptance criteria

- [ ] A `self_repair` slot exists (Protocol + `rule_based_repair` provider), `safe_noop`; with
      `infra_monitor` unavailable, `run_once()` returns a typed empty cycle, never raises.
- [ ] `evaluate(health)` is pure (no side effects) and maps each rule-table symptom to the expected
      `RepairProposal` (action + tier); unknown symptoms yield **no** proposal (`undiagnosed`).
- [ ] An `unhealthy` container yields a `restart_container` proposal; with `auto_safe` it executes
      via `infra_action` without approval (reversible tier).
- [ ] A `restarting` (crash-loop) container is **propose-only** (never auto-restarted), and a
      `stopped` container yields **no** proposal (intentional absence).
- [ ] Under `autonomy=approve_all`, a reversible remediation is **blocked pending approval** and only
      executes after the `approval` slot resolves — end-to-end with the baseline inbox (deny → no-op).
- [ ] Storage not-healthy produces a **propose-only** result (no action dispatched) and an escalation
      event.
- [ ] Safety governor: after the per-resource attempt budget is exhausted within the window,
      `run_once()` dispatches **no** further action for that resource and emits an escalation
      (tested with a resource that stays down across cycles).
- [ ] Flap detection: a resource that oscillates recover↔fail stops being auto-remediated and is
      escalated.
- [ ] `detect_only` autonomy: proposals are produced and recorded, but **zero** actions dispatched.
- [ ] Disabling the slot (kill-switch) halts all action immediately (slot `resolve` → baseline/noop).
- [ ] Every acted/suppressed/escalated decision produces an audit entry with the full record shape.

## Testing

- Unit: rule-table diagnosis per `(resource, status, signal)`; `evaluate()` purity; governor
  decisions (budget exhaustion, cooldown, flap, in-flight guard) with a fake clock.
- Contract: `SelfRepair` conforms to its slot Protocol (SPEC-184); it dispatches **only** through
  `infra_action` (asserted — no direct host calls).
- Integration: full `run_once()` against a **fake `infra_monitor`** feeding scripted health and a
  **fake `infra_action`** recording dispatches; reversible auto-runs, destructive blocks→approve→runs,
  storage propose-only, budget/flap escalate. Reuse the SPEC-187 fake host API where convenient.
- Property (formal/): "a `destructive` remediation never executes without a resolved approval";
  "per-resource actions within a window never exceed the budget"; "no action outside the
  `infra_action` allowlist is ever dispatched"; "`detect_only` dispatches nothing".

## Open questions

- **Notification of escalations.** When the governor escalates (budget/flap/storage), how is the
  human told beyond the inbox — reuse a `notify` slot (HA push / email) when present? Default: inbox
  + event; `notify` is best-effort if active.
- **Diagnosis confidence + LLM role.** Should low-confidence rule matches route to `approval` even
  for reversible tiers? Leaning yes (treat uncertainty as risk). The LLM explanation step is
  advisory-only in v1; promoting it to *propose* actions is a later, separately-gated decision.
- **Cross-resource root cause.** A single root cause (host OOM) can degrade many resources; v1 treats
  resources independently (and the per-cycle action cap limits storms). Correlation/root-cause
  grouping is deferred.
- **Backups visibility.** SPEC-187 noted `/full` lacks a `backups` section; self_repair cannot
  remediate what it cannot observe — depends on a host-API `backups`/PBS endpoint (host-side task).
- **Persistence of governor state.** Attempt counters/cooldowns are in-memory in v1 (reset on
  restart); persist to survive restarts? Defer until the loop is proven.

## References

- [SPEC-184: Modular capability platform](SPEC-184-modular-capability-platform.md) — slots, fallback, autonomy.
- [SPEC-187: Infra control, monitoring & approval](SPEC-187-infra-control-monitor-approval.md) — the primitives self_repair composes.
- [SPEC-011: vault](SPEC-011-vault.md) — host-health bearer token at rest.
- ADR-038 — reliability taxonomy & circuit-breaking (`maistro.resilience`: backoff, error classification) reused by the safety governor.
- Phase 1b PR (#86) — capability wiring that makes `infra_monitor`/`infra_action`/`approval` live in the running engine.
