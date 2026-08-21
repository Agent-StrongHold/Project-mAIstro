---
id: SPEC-062126-6a31
title: "Memory exposure mode: mandatory declaration, write/promote enforcement (ADR-057)"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-06-21
substrate:
  - maistro-engine#ADR-011
  - maistro-engine#ADR-014
  - maistro-engine#ADR-057
  - maistro-engine#SPEC-249
implements:
  - maistro-engine#ADR-057
related:
  - maistro-engine#ADR-019
  - maistro-engine#ADR-053
  - maistro-engine#SPEC-227
  - maistro-engine#SPEC-062126-5d56
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/memory/test_exposure_mode.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-062126-6a31: Memory exposure mode enforcement

## Context

SPEC-249 (Implemented) already built the load-bearing primitive ADR-057 calls for:
`Actor`/`MemoryExposureMode`/`BlockExposure` enums and pure `enforce_write`/`enforce_promote`
functions in `maistro/memory/exposure.py`. SPEC-249 deliberately stopped short of two things
and named them as its own follow-up, since "no concrete store calls this gate yet": (1)
wiring `enforce_write`/`enforce_promote` into an actual `MemoryStore`, and (2) the
"default mode for callers that don't specify one, and the deprecation-warning migration path"
— SPEC-249's own words for exactly ADR-057's open questions 2/3. This SPEC is that follow-up.

It resolves the declaration question as **mandatory declaration with no implicit default**:
every agent instance must declare `memory.exposure_mode` in its recipe (ADR-053 overlay)
before it can call `enforce_write`/`enforce_promote` (or read memory) at all. There is
deliberately no "safe default" to fall back on, because a default that fits one product
(e.g. maistro-turing's existing implicit read+write+promote loop) is wrong for another (a
curated-context product), and ADR-019/030 forbid engine code from knowing which product
it's running inside to pick between them. Mandatory declaration sidesteps the choice
entirely: maistro-turing's `agent.yaml` declares `agent_managed` explicitly (matching its
existing behavior, now made visible rather than implicit), and any curated-context
product declares `system_managed` explicitly — both correct, neither inferred.

## Goals

- Resolve ADR-057's open question 2/3 (default mode / migration path) as: **no implicit
  default; declaration is mandatory; an agent instance with no declared mode cannot
  perform any memory operation** — replaces the ADR's own "implicit AGENT_MANAGED +
  deprecation warning" recommendation with a fail-fast model instead.
- Resolve open question 1 (`HYBRID` as distinct enum vs. emergent): keep `HYBRID` explicit,
  per the ADR's own recommendation — no change needed, just confirming.
- Resolve open question 4 (per-scope override): agent-instance-level only for v0, per the
  ADR's own recommendation — no change needed, just confirming.
- Resolve open question 5 (promotion under `SYSTEM_MANAGED`): admin-only for v0, per the
  ADR's own recommendation — no change needed, just confirming.
- Specify the concrete `MemoryUndeclaredModeError` raised when an agent instance with no
  declared mode attempts any `read`/`write`/`promote` call.
- Specify how `AgentConfig`/recipe loading surfaces the missing-declaration error at
  agent-construction time (fail at load, not at first memory call) where possible, falling
  back to per-call enforcement for dynamically-constructed agents.

## Non-goals

- Admin UI for curating `SYSTEM_MANAGED` blocks (ADR-057's own out-of-scope, unchanged).
- Cross-tenant memory sharing (Stronghold concern, unchanged).
- Gate-mediated agent-suggests-admin-approves promotion under `SYSTEM_MANAGED` (ADR-057's
  own out-of-scope, unchanged) — admin-only promotion stands for v0.
- Decay/consolidation/cross-scope dynamics — covered by SPEC-062126-5d56, orthogonal to exposure
  mode (a memory can be `AGENT_MANAGED` and still decay/consolidate per SPEC-062126-5d56; the two
  SPECs don't interact).

## Decision

### Mandatory declaration, no default

```python
class MemoryUndeclaredModeError(Exception):
    """Raised when an agent instance with no declared exposure_mode attempts any
    memory operation. There is no implicit default (supersedes ADR-057's own
    'implicit AGENT_MANAGED + deprecation warning' recommendation)."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(
            f"Agent '{agent_id}' has no declared memory.exposure_mode; "
            "declare one explicitly in its recipe before it can use memory."
        )
```

A `MemoryStore`'s `exposure_mode` field is typed `MemoryExposureMode | None`, defaulting to
`None`. Every `read`/`write`/`promote` call checks `exposure_mode is not None` first —
before calling SPEC-249's `enforce_write`/`enforce_promote` (which require a concrete
`MemoryExposureMode`, not `None`, as their first argument) — and raises
`MemoryUndeclaredModeError` if unset. This is a hard requirement from day one — there is
no deprecation window, per the decision to skip ADR-057's phased-migration
recommendation. `enforce_write`/`enforce_promote` themselves are unchanged by this SPEC;
this is purely the caller-side gate that decides whether they get called at all.

### Enforcement matrix (unchanged from ADR-057, restated for completeness)

| Mode | `read` | `write(actor=AGENT)` | `write(actor=SYSTEM)` | `promote(actor=AGENT)` |
|---|---|---|---|---|
| `SYSTEM_MANAGED` | allowed | denied (`MemoryWriteDenied`) | allowed | denied |
| `AGENT_MANAGED` | allowed | allowed | allowed | allowed |
| `HYBRID` | allowed | per-block `exposure` tag | allowed | per-block tag |

### Recipe-time fail-fast

```python
def load_agent_config(recipe: dict[str, Any]) -> AgentConfig:
    memory_cfg = recipe.get("memory", {})
    if "exposure_mode" not in memory_cfg:
        raise MemoryUndeclaredModeError(agent_id=recipe["agent_id"])
    ...
```

Recipes loaded through `AgentConfig`/`container.py` fail at construction time, surfacing
the error before the agent ever runs. Agents constructed dynamically without going through
recipe loading (rare; e.g. some test harnesses) fall back to the per-call check in
`MemoryStore` — `MemoryUndeclaredModeError` is the same exception either way, just raised
at a different point in the lifecycle.

### maistro-turing migration

`packages/maistro-turing/`'s agent definitions add `memory: {exposure_mode:
agent_managed}` to their recipes in the same change that ships this SPEC — required
immediately, not a deprecation-window migration, since there is no implicit fallback for
them to rely on in the interim.

## Acceptance criteria

- [ ] An agent instance with no declared `exposure_mode` raises `MemoryUndeclaredModeError`
      on any `read`/`write`/`promote` call — never silently defaults to either mode.
- [ ] `load_agent_config` raises `MemoryUndeclaredModeError` at recipe-load time when
      `memory.exposure_mode` is absent, for recipes that declare a `memory` block at all
      or omit it entirely.
- [ ] Agent `write` under `SYSTEM_MANAGED` raises `MemoryWriteDenied` (ADR-057, unchanged).
- [ ] System `write` under any mode succeeds (ADR-057, unchanged).
- [ ] Agent `write`/`promote` under `AGENT_MANAGED` succeeds and persists (ADR-057,
      unchanged).
- [ ] `HYBRID` mode honours per-block `exposure` tags (ADR-057, unchanged).
- [ ] `packages/maistro-turing/` agent recipes all declare `exposure_mode: agent_managed`
      and construct successfully with no `MemoryUndeclaredModeError`.
- [ ] Mode and `memory.write.denied{scope, actor, mode, reason}` events recorded per
      ADR-037 (unchanged from ADR-057).
- [ ] No engine code path branches on product identity to pick a mode (governance check;
      grep for product-name string literals in `maistro.memory`).

## Testing

`packages/maistro-core/tests/memory/test_exposure_mode.py` already exists (SPEC-249's test
file, covering the enforcement matrix for `enforce_write`/`enforce_promote`). This SPEC
extends that same file with new test classes rather than creating a new one: undeclared-mode
raises on each of read/write/promote; recipe-load-time failure for missing
`memory.exposure_mode` key; `HYBRID` per-block tag honouring (already covered by SPEC-249,
re-asserted here only at the store-wiring level); governance grep test (no product-identity
string literals in `maistro.memory.*`).

- Existing maistro-turing test suite re-run after adding `exposure_mode: agent_managed` to
  its fixture recipes, to confirm no regression from the new fail-fast check.

## Open questions

- Whether dynamically-constructed agents that bypass recipe loading (some test harnesses)
  should also gain a recipe-equivalent fail-fast path, or whether the per-call check is
  sufficient for them — left to the implementation PR; the acceptance criteria above only
  require recipe-load-time failure where a recipe is actually loaded.

## References

- [ADR-057: Memory exposure mode](../adr/ADR-057-memory-exposure-mode.md)
- [SPEC-062126-5d56: Memory dynamics](SPEC-062126-5d56-memory-dynamics-decay-consolidation.md) — orthogonal,
  decay/consolidation mechanics independent of exposure mode.
- `packages/maistro-turing/src/maistro_turing/` — agent-managed precedent needing migration.
