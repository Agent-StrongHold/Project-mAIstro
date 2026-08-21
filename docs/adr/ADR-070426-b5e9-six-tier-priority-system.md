---
id: ADR-070426-b5e9
title: Six-tier priority system (P0-P5) — cross-cutting priority_tier label
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-07-04
substrate:
  - maistro-engine#ADR-010
related:
  - maistro-engine#ADR-046
  - maistro-engine#ADR-079
  - maistro-engine#ADR-085
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
    date: 2026-07-04
---

# ADR-070426-b5e9: Six-tier priority system (P0-P5)

## Context

Five maistro-engine subsystems each need an answer to "how important is this request, and how
much should the platform spend on it": routing (`maistro.router.scorer.score_candidate`, which
already reads `routing_cfg.priority_multipliers.get(intent.tier, 1.0)` at
`packages/maistro-core/src/maistro/router/scorer.py:79`), token budgeting, quota accounting
(`maistro.quota`), observability/alerting, and task-queue shedding (`maistro.tasks.queue`). Without
a shared label these subsystems drift: a request the router treats as high priority (flagship
model, generous token budget) but the task queue treats as low priority (pruned first under
load) is a coherence bug, not a feature.

The classifier already infers a six-value tier — `maistro.classifier.complexity.infer_priority`
returns `Literal["P0", ..., "P5"]`, and its docstring cites the tier semantics "per ADR-K8S-014"
(Stronghold's homelab-era six-tier priority ADR, `ADR-K8S-014-six-tier-priority-system.md`) — and
`RoutingConfig.priority_multipliers` (`packages/maistro-core/src/maistro/types/config.py:12-21`)
already ships P0=1.5x down to P5=0.7x defaults, and `AgentConfig.priority_tier`
(`packages/maistro-core/src/maistro/types/agent.py:33`) already carries the same six literals.
What is missing is the ADR that ratifies `priority_tier` as the one cross-cutting label every
subsystem reads, states what each tier means outside routing, and — critically — removes the
Kubernetes-specific machinery (`PriorityClass`, `minReplicas`, pod eviction) that ADR-K8S-014/015
bundled in, because maistro-engine has no Kubernetes layer and is not the place that owns one.

ADR-010 already introduced a coarser scheduling axis, `Lane` (`LIVE` vs `BACKGROUND`), splitting
`TaskRunner` worker slots. Lanes and tiers are not the same axis and this ADR does not replace
lanes: a lane is *where* a task runs (fast-lane reserved slot vs background pool); a tier is *how
much* the platform should spend on it once it's running. Both P0 and P2 requests can be LIVE lane;
they still deserve different routing weight and token budget.

## Decision

**`priority_tier` (`Literal["P0", "P1", "P2", "P3", "P4", "P5"]`) is the cross-cutting label every
priority-aware subsystem in maistro-engine reads.** The pre-existing four-value `intent.priority`
enum (`low`/`normal`/`high`/`critical`, used by `maistro.classifier`) is repurposed as a
routing-only signal that feeds `infer_priority`/`coerce_priority`; `priority_tier` is what flows
through token budgets, quota, observability, and task-queue retention.

### The six tiers

| Tier | Name | Surface | Routing weight | Model bias | Token budget | Cold-start | Queue retention | SLA / alert |
|------|------|---------|-----------------|------------|---------------|------------|------------------|-------------|
| P0 | chat-critical | in-process conversational turn | 1.5x | flagship | 2.0x base | 0s — always warm | LAST pruned | <2s p99 / page |
| P1 | chat-tools | chat turn invoking kept-warm tool calls | 1.2x | flagship | 1.5x base | <2s warm pool | after P2-P5 | <5s p99 / page |
| P2 | user-missions | user-submitted agentic work (mission/refactor) | 1.0x | balanced | 1.0x base | 30s acceptable | after P3-P5 | <60s p99 / log+retry |
| P3 | backend-support | scheduled/event-driven maintenance | 0.9x | fast-cheap | 0.5x base | 30s+ | after P4-P5 | best-effort / log |
| P4 | quartermaster | supervising agent decomposing a parent issue | 0.8x | balanced | 1.0x base | 30s+ | after P5 | best-effort / log+retry |
| P5 | builders | implementer sub-issue agents | 0.7x | fast-cheap/code-capable | 0.5x base | minutes acceptable | FIRST pruned | best-effort / log+retry |

Routing weights above are the values already shipping in
`RoutingConfig.priority_multipliers` — this ADR ratifies them as the canonical table rather than
an implementation default that could silently drift; it does not change the numbers. (Stronghold's
`ADR-K8S-014` proposed 2.0x for P0; the engine's own routing-quality math converged on 1.5x during
implementation — see `router/scorer.py` — and this ADR keeps the shipped value rather than
re-deriving a new one.)

### How the tiers map to real work

Same mapping `infer_priority` and `AgentConfig.priority_tier` already assume: P0/P1 are
conversational (in-process or warm-tool-pod); P2 is user-facing agentic mission work; P3 is
platform housekeeping (janitors, quota reconcilers, `maistro.scheduling`); P4/P5 are the
orchestrator/builder split inside `maistro.orchestrator` (Master Orchestrator decomposes into
sub-issues at P4, builder agents execute them at P5).

### Token budget multiplier

Each tier multiplies a base per-task-type token budget (`TaskTypeConfig`, `types/config.py`). P0
gets 2.0x the base context window; P5 gets 0.5x. This is a new config field
(`RoutingConfig.token_budget_multipliers`, mirroring the shape of `priority_multipliers`) — not yet
wired into the context builder; tracked as a SPEC follow-up, not decided here.

### Cold-start policy

"Cold-start" in maistro-engine terms is agent/session warm-up latency, not pod scheduling: P0/P1
sessions should avoid cold classifier/router paths (a following SPEC may pre-warm session state);
P2 and below tolerate the full classify → route → dispatch path cold. No code changes decided
here beyond naming the policy axis.

### Queue retention (the de-K8s'd replacement for "eviction order")

`maistro.tasks.queue.TaskQueue` already prunes terminal tasks past `MAX_TASK_STORE_SIZE` down to
`PRUNE_TARGET` (`packages/maistro-core/src/maistro/tasks/queue.py:29-33`), currently
FIFO-by-insertion with no priority awareness. This ADR decides that pruning (and, if the queue
ever needs to shed *pending* work under backpressure, shedding) should consult `priority_tier`:
prune/shed P5 first, P0 last. This is an in-process retention policy, not a Kubernetes eviction
policy — there are no pods, no `PriorityClass`, no `minReplicas` here. **Downstream Stronghold**,
which runs on Kubernetes, is free to map P0-P5 onto its own `PriorityClass`/QoS scheme (as
`ADR-K8S-014`/`ADR-K8S-015` describe) — that mapping is Stronghold-owned per ADR-019/ADR-035 and is
explicitly out of scope here.

### SLA / observability

`priority_tier` becomes a required label on router/quota/task observability spans
(`maistro.observability`) so an operator can filter "what's affected" by tier. P0/P1 breaches page;
P2 logs and retries; P3-P5 log best-effort. No new alerting infrastructure decided here — this
states the label that alerting rules will key off once written.

## De-K8s'd: explicit non-goals

This ADR explicitly does **not** decide, and strips out of the six-tier table relative to
`ADR-K8S-014`/`ADR-K8S-015`:

- `PriorityClass` numeric values, `minReplicas`, `PodDisruptionBudget` — maistro-engine has no
  Kubernetes deployment surface to attach these to.
- Pod-eviction order under node-memory pressure — replaced above by in-process task-queue
  retention, a materially different mechanism operating on a materially different resource
  (process memory / task slots, not cluster nodes).
- Helm chart values, `values-prod-homelab.yaml` — Stronghold-owned deployment concern.

Stronghold (ADR-019, ADR-068's tenancy split) inherits `priority_tier` as-is from the engine and
may re-attach its own Kubernetes scheduling machinery on top, per `ADR-K8S-014`/`ADR-K8S-015`. It
does not need a different tier taxonomy — only a different enforcement mechanism for the same six
labels.

## Alternatives considered

**A) Keep only the four-value `intent.priority` enum and let each subsystem interpret it.**
Rejected — this is the status quo that motivated this ADR; "high" cannot cleanly distinguish
chat-critical from user-missions, which want different token budgets and queue retention.

**B) Per-subsystem priority schemes reconciled by convention, not a shared label.** Rejected —
convention drifts; the router and the task queue would eventually disagree about what "P1" means
with no compile-time or CI check to catch it.

**C) Port `ADR-K8S-014`/`ADR-K8S-015` verbatim, including the Kubernetes columns.** Rejected — the
engine has no Kubernetes layer; carrying `PriorityClass`/`minReplicas` columns in an engine ADR
would document infrastructure that doesn't exist here and would need to be re-decided (differently)
when Stronghold actually deploys to K8s.

**D) A continuous priority score instead of six discrete tiers.** Rejected for the same reason
`ADR-K8S-014` rejected it: `infer_priority` and `priority_tier` already exist as six discrete
literals in shipped code; introducing a continuous score would require bucketing back down to
these six values at every consumer anyway.

## Consequences

**Positive:**
- Routing, token budgets, quota, observability, and task-queue retention read the same label;
  they cannot silently disagree about what "P1" means.
- `router/scorer.py`'s existing `priority_multipliers` table is now a ratified decision, not an
  unreviewed default.
- Adding a new workload means picking one of six tiers, not inventing a scheme.

**Negative:**
- Token-budget multiplier and priority-aware queue retention are named here but not yet wired to
  code — follow-up SPEC work is required before the ADR is fully implemented.
- `maistro.observability` spans need a `priority_tier` label added, a small but repo-wide change.

**Trade-offs accepted:**
- We accept documenting a partially-already-implemented mechanism (routing) alongside
  not-yet-implemented ones (token budget, queue retention) in one ADR, because the six-tier
  taxonomy itself — not each consumer — is the thing that needs to be singular and agreed.

## References

- [ADR-010: Lane-based scheduling (LIVE vs BACKGROUND)](ADR-010-lane-scheduling.md)
- [ADR-046: Scheduler — Recurring agent tasks](ADR-046-scheduler.md)
- [ADR-079: LLM Provider / Model Registry, Routing, and Embeddings](ADR-079-model-registry-routing-embeddings.md)
- [ADR-085: Cost, Quota, and Rate Limiting](ADR-085-cost-quota-rate-limiting.md)
- Stronghold `ADR-K8S-014` (six-tier priority system) and `ADR-K8S-015` (PriorityClass eviction
  order) — origin of the tier taxonomy and naming; superseded here for the engine by stripping
  Kubernetes-specific mechanism, kept as the reference for Stronghold's own downstream mapping.
- Seams: `router/scorer.py:79`, `types/config.py:12-21`, `types/agent.py:33`,
  `classifier/complexity.py:78-92`, `tasks/queue.py:29-33`.
