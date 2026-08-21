---
id: ADR-054
title: Agent sandbox lifecycle and task budget enforcement
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-13
substrate:
  - maistro-engine#ADR-018
  - maistro-engine#ADR-038
  - maistro-engine#ADR-049
  - maistro-engine#ADR-051
implements: []
related:
  - maistro-engine#ADR-028
  - maistro-engine#ADR-052
  - maistro-engine#ADR-056
  - maistro-engine#ADR-068
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-13
---

# ADR-054: Agent sandbox lifecycle and task budget enforcement

## Context

`src/maistro/tools/sandbox/` exists and pyproject pulls in `docker>=7.0`. There is no ADR specifying when a sandbox is provisioned, how long it lives, where its durable state lives, or how per-task budgets (cost, wall-clock, step count, tokens) are enforced. ADR-038 ships reliability primitives but not task-level budget enforcement. ADR-028 covers process privilege but not sandbox lifecycle.

Production agent systems converge on one-sandbox-per-task with ephemeral FS + external durable stores for v0, with optional warm-pool optimisation later. Budgets compose with ADR-051 approval gates — "approve another \$1?" — applying plan-level approval to spend.

## Problem

No specified sandbox lifecycle, no specified state-persistence boundary, no specified budget-enforcement model.

## Decision

### Provisioning model

**One sandbox container per task.** Fresh container at task start; teardown at task completion. Strong isolation; no cross-task leakage. Cold-start cost accepted for v0; warm-pool deferred to a follow-up ADR if cold-start latency exceeds 3s p50 at production volumes.

Sandbox tier is recipe-declared as a small enum (`small | large | gpu`) mapped substrate-side to concrete container specs. Recipe knob (`merge: replace` per ADR-053):

```yaml
sandbox:
  tier: small | large | gpu
```

### State persistence boundary

Sandbox FS is **ephemeral scratch** — nothing important lives there. Durable state lives in services already shipped by the engine:

| Concern | Durable store |
|---|---|
| Shadow git workspace | Local FS path mounted into the sandbox (ADR-049) |
| `TaskRecord` and checkpoints | Postgres (ADR-018) |
| Memory blocks | Postgres / vector store (ADR-011/034) |
| Cumulative spend per task | `TaskRecord` field (this ADR) |
| Observability events | APM + narrow event log (ADR-037 / ADR-055) |

A sandbox crash mid-task leaves all durable state intact; ADR-056 resumes from the checkpoint stream.

### Parallel waves

Waves from ADR-052 run as concurrent processes inside the same task sandbox, sharing the FS. Shadow-git per-wave branches handle file-level isolation. Per-wave separate sandboxes are out of scope for v0.

### Budget enforcement (hard-with-escalation)

Recipe declares per-task limits (`merge: deep`):

```yaml
limits:
  max_tokens: 200_000
  max_dollars: 5.00
  max_wall_clock_s: 600
  max_steps: 50
```

Substrate tracks cumulative spend per resource on `TaskRecord.cumulative_spend`. At 80% of any declared limit, substrate raises an approval gate (ADR-051) — "approve another $X?". At 100%, substrate kills the task with `TaskBudgetExceeded`.

Cumulative spend persists across crashes. A task resumed at 75% (ADR-056) starts at 75%, not 0%. Per-resource thresholds independently checked; if multiple thresholds trip in the same window the prompt collapses (ADR-051).

## Interface (sketch)

```python
class SandboxTier(StrEnum):
    SMALL = "small"
    LARGE = "large"
    GPU = "gpu"

class SandboxLifecycle(Protocol):
    async def provision(self, task: TaskRecord, recipe: AgentRecipe) -> SandboxHandle: ...
    async def teardown(self, handle: SandboxHandle) -> None: ...

class BudgetState(BaseModel):
    resource: str
    consumed: Decimal
    limit: Decimal | None
    fraction: float    # consumed / limit; > 0.8 triggers escalation

class BudgetTracker(Protocol):
    async def consume(self, task_id: UUID, resource: str, amount: Decimal) -> BudgetState: ...
    async def state(self, task_id: UUID) -> dict[str, BudgetState]: ...
```

## Acceptance criteria

- [ ] Task with no `limits` declared runs without budget enforcement (back-compat).
- [ ] Crossing 80% of any declared limit raises one approval gate (ADR-051); collapsed if multiple trip.
- [ ] Crossing 100% kills the task with `TaskBudgetExceeded`; durable state preserved.
- [ ] Resumed task (ADR-056) starts with cumulative spend intact.
- [ ] Sandbox provisioning time tracked: metric `maistro_sandbox_provision_duration_seconds{tier}` per ADR-037.
- [ ] Span `sandbox.provision`, `sandbox.teardown` per ADR-037.
- [ ] Recipe-declared `sandbox.tier` resolved to a concrete container spec at provision time.
- [ ] Sandbox FS not used for any durable artefact (CI check via observability — sandbox-FS writes outside `/scratch` raise a `sandbox.fs.unexpected_write` event).

## Resolved decisions (v0)

1. **Sandbox tier mapping → substrate ships the enum + a default mapping.** The engine ships sensible default container specs per `(small | large | gpu)`; concrete specs are product-tunable via config rather than blocking on product input.
2. **Cold-start mitigation → measure first.** If sandbox provision p50 exceeds 3s at volume, ship per-recipe pre-baked images for the top-N most-used recipes.
3. **Per-tool fine-grained resource limits inside the sandbox → out of scope (v0).** Recipe-level (per-task) budget only.
4. **Composite vs per-resource budget approval → collapse.** When multiple thresholds trip in the same wall-clock window, collapse to a single approval prompt (per ADR-051).
5. **GPU provisioning → recipe declares `tier: gpu`; substrate routes to a GPU node pool.** Specific node-pool selection is a product/infra concern.

## Source references

- `maistro-engine:src/maistro/tools/sandbox/` (existing module).
- `maistro-engine:Dockerfile`, `docker-compose.yml` (current sandbox shape).
- ADR-018 (TaskRecord — gains `cumulative_spend` and `workspace_ref` fields).
- ADR-038 reliability (circuit-breaker on provider overspend is orthogonal).
- ADR-049 shadow git (FS mounted into sandbox).
- ADR-051 approval gates (budget escalation reuses the same surface).

## Out of scope

- Warm-pool / per-tenant long-lived sandboxes (revisit if cold-start hurts).
- Specific GPU node-pool routing (infra/product concern).
- Cross-tenant sandbox sharing (stronghold concern).
- Inside-sandbox per-tool resource limits.
