---
id: SPEC-244
title: "ContextAssemblyPolicy — Layer 0-4 memory assembly (ADR-091)"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-013
  - maistro-engine#ADR-016
  - maistro-engine#ADR-034
implements:
  - maistro-engine#ADR-091
related:
  - maistro-engine#SPEC-177
  - maistro-engine#SPEC-189
  - maistro-engine#SPEC-193
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/memory/test_context_assembly.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-244: ContextAssemblyPolicy — Layer 0-4 memory assembly

## Context

ADR-091 distinguishes Level 1 storage types (`EpisodicMemory`, `Learning`, `Outcome`,
`SkillMutation`) from Level 2 context-assembly layers (0-4, describing how those stores
are concatenated into an LLM prompt). No `ContextAssemblyPolicy` protocol or
implementation exists today — `maistro.protocols.memory` has `EpisodicStore`,
`OutcomeStore`, `SessionStore`, etc., but nothing that assembles them into layered
prompt text. `Project` (`maistro/projects/types.py`) has no `constraints_text` field;
it has `profile_markdown`, which serves the same role ADR-091 assigns to Layer 0.

This SPEC scopes a minimal, protocol-driven default implementation: the
`ContextAssemblyPolicy` protocol plus a `DefaultContextAssemblyPolicy` that wires
Layers 0, 1, and 3 to existing stores (`Project.profile_markdown`, `EpisodicStore`,
`OutcomeStore`). Layer 2 (SPEC-189 rolling compression) and Layer 4 (knowledge graph)
are not yet implemented elsewhere, so this SPEC's default policy returns `""` for
both, matching ADR-091's own stated fallback for Layer 4 and extending the same
fallback to Layer 2 until SPEC-189 lands.

## Goals

- Add `ContextAssemblyPolicy` Protocol to `maistro/protocols/memory.py`, matching
  ADR-091's interface (`layer0`..`layer4`, `assemble`).
- Add `DefaultContextAssemblyPolicy` in `maistro/memory/context_assembly.py` implementing:
  - `layer0`: returns `project.profile_markdown` (Project's existing field serves
    ADR-091's "pinned constraints" role; no schema change).
  - `layer1`: queries `EpisodicStore.retrieve(...)` scoped to `agent_id`/`session_id`,
    filtered to weight ≥ 0.3 (excludes OBSERVATION/HYPOTHESIS by default per ADR-091),
    formatted as text.
  - `layer2`: returns `""` (SPEC-189 not yet implemented — explicit placeholder, not
    a silent gap).
  - `layer3`: `OutcomeStore.get_experience_context(...)` text (project-scoped, via
    `project_id`) plus WISDOM-tier (weight ≥ 0.9) episodic memories filtered by the
    new `EpisodicMemory.project_id` field (see Decision — added as part of this SPEC
    after review; superseded ADR-091's original "no schema change" framing for this
    one additive field).
  - `layer4`: returns `""` (per ADR-091, deferred).
  - `assemble`: concatenates layers 0-4 in order; Layer 0 never truncated; layers 1-3
    truncated (3 first) by a simple token-estimate (`len(text) // 4`) against
    `budget_tokens`.
- Wire `ContextAssemblyPolicy` into `Container` (`maistro/container.py`) following the
  existing `learning_store`/`outcome_store` field pattern.

## Non-goals

- Implementing SPEC-189 rolling compression or SPEC-193 cache-key plumbing — Layer 2
  stays a placeholder.
- Knowledge graph (Layer 4) — stays a placeholder per ADR-091.
- Adding a `constraints_text` field to `Project` — reuses `profile_markdown`.
- `WorkingMemoryProtocol` (SPEC-177) — Layer 1 in this SPEC is episodic-only; wiring
  graph-run working memory into Layer 1 is SPEC-177's job when it lands.

## Decision

`EpisodicStore.retrieve()` requires word-overlap with `query` (overlap must be > 0 to
match), so it cannot return "all scoped memories regardless of content" — but
ADR-091 requires Layer 1/3 to *always* include REGRET/AFFIRMATION/WISDOM tiers
unconditionally, independent of any query match. This SPEC therefore adds one new
method to `EpisodicStore` (additive, not a breaking change):

```python
async def list_by_scope(
    self, *, agent_id: str | None = None, team_id: str | None = None,
    org_id: str | None = None, project_id: str | None = None,
    min_weight: float = 0.0, limit: int = 50,
) -> list[EpisodicMemory]:
    """Scope-filtered memories at or above min_weight, no content matching."""
```

implemented in `InMemoryEpisodicStore` alongside `retrieve`, reusing
`build_scope_filter`/`matches_scope`. When no `agent_id`/`team_id`/`org_id` is given
(project-changelog recall with no caller-identity context), scope filtering is
skipped and `project_id` alone selects memories.

Also adds `EpisodicMemory.project_id: str = ""` (`maistro/types/memory.py`) — an
additive, default-empty field, decided after explicit review (see Open questions in
the prior revision of this SPEC) to make Layer 3 genuinely project-scoped rather than
approximated by team/agent scope. `project_id` is independent of the
`scope`/`org_id`/`team_id`/`agent_id`/`user_id` visibility axis; it answers "which
project does this pertain to," not "who can see it."

```python
# maistro/protocols/memory.py — new protocol
class ContextAssemblyPolicy(Protocol):
    async def layer0(self, project_id: str) -> str: ...
    async def layer1(self, run_id: str, agent_id: str, session_id: str) -> str: ...
    async def layer2(self, session_id: str, budget_tokens: int) -> str: ...
    async def layer3(self, project_id: str, n: int = 20) -> str: ...
    async def layer4(self, project_id: str) -> str: ...
    async def assemble(
        self, project_id: str, run_id: str, agent_id: str, session_id: str,
        budget_tokens: int,
    ) -> str: ...
```

`DefaultContextAssemblyPolicy.__init__` takes `episodic_store: EpisodicStore`,
`outcome_store: OutcomeStore`, `project_store` (existing project lookup), injected —
matching the protocol-driven DI convention. Weight-band filtering (≥0.6 always,
0.3-0.59 budget-permitting, <0.3 excluded) is applied in `layer1`/`layer3` per
ADR-091's table, using `EpisodicMemory.weight` directly (no new query parameter
needed on `EpisodicStore` — the policy filters the returned list itself).

## Acceptance criteria

- [x] `ContextAssemblyPolicy` protocol exists in `maistro/protocols/memory.py` with
      the exact method signatures from ADR-091.
- [x] `DefaultContextAssemblyPolicy.layer1` excludes OBSERVATION/HYPOTHESIS-tier
      memories (weight < 0.3) and includes REGRET/AFFIRMATION/WISDOM unconditionally.
- [x] `DefaultContextAssemblyPolicy.layer3` includes only WISDOM-tier (weight ≥ 0.9)
      episodic memories (project-scoped via `project_id`), plus `Outcome`
      experience-context text (project-scoped via `project_id`).
- [x] `layer2` and `layer4` return `""` unconditionally (documented placeholders).
- [x] `assemble` concatenates layers in order 0,1,2,3,4; Layer 0 content is never
      dropped even when `budget_tokens` is smaller than its length.
- [x] `Container` exposes a `context_assembly_policy: ContextAssemblyPolicy` field
      wired to `DefaultContextAssemblyPolicy` in `create_container()`.

## Testing

- `packages/maistro-core/tests/memory/test_context_assembly.py` (new) — unit tests
  against `DefaultContextAssemblyPolicy` using `InMemoryEpisodicStore`/
  `InMemoryOutcomeStore` fakes: weight-band filtering for layer1/layer3, placeholder
  behavior for layer2/layer4, assemble ordering + Layer 0 non-truncation.

## Open questions

- Whether `layer1`'s scope filter (`scope ∈ {AGENT, SESSION}`) needs a new
  `EpisodicStore.retrieve` parameter or can be done by post-filtering the existing
  `retrieve()` result — left as post-filtering for this SPEC since `EpisodicStore`
  already accepts `agent_id`; revisit if retrieval volume makes post-filtering
  wasteful.

## References

- `packages/maistro-core/src/maistro/protocols/memory.py`
- `packages/maistro-core/src/maistro/memory/episodic/store.py`
- `packages/maistro-core/src/maistro/memory/outcomes.py`
- `packages/maistro-core/src/maistro/projects/types.py`
- `packages/maistro-core/src/maistro/container.py`
- [ADR-091: Memory model reconciliation](../adr/ADR-091-memory-model-layers.md)
