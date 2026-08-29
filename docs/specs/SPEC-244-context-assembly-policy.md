---
id: SPEC-244
title: "ContextAssemblyPolicy — Layer 0-4 memory assembly (ADR-091)"
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-06-20
history:
  - status: Accepted
    date: 2026-06-20
  - status: AC Defined
    date: 2026-08-29
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
  - packages/maistro-core/tests/memory/test_ranked_recall.py
source:
  - packages/maistro-core/src/maistro/memory/context_assembly.py
ac-modules:
  AC-1: maistro.memory.context_assembly
  AC-2: maistro.memory.episodic.retrieval
  AC-3: maistro.memory.context_assembly
  AC-4: maistro.memory.context_assembly
  AC-5: maistro.agents.context_builder
  AC-6: maistro.memory.episodic.ranking
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

The prose checklist this section used to carry was true of the protocol and
false of the behaviour: it claimed layer1 "includes REGRET/AFFIRMATION/WISDOM
unconditionally" while `assemble` sliced the joined layer text by character, so
an always-include memory could be dropped or halved by a budget it is exempt
from. #622 made the claim true and restates it here in the form the AC gate
reads, so it is checkable rather than asserted.

```gherkin
@AC-1
Scenario: A prompt layer is assembled by relevance, not by insertion order
  Given episodic memories whose store order differs from their relevance to the run
  When Layer 1 is assembled for a run with a query
  Then the memories present are the ones scoring highest for that query
  And reversing the insertion order does not change the answer

@AC-2
Scenario: Ranked retrieval works against a store it did not construct
  Given an episodic store that is not the in-memory implementation
  When scored retrieval runs against it
  Then it returns ranked memories through the EpisodicStore protocol
  And the scope axes it was given reach the store rather than being applied afterwards

@AC-3
Scenario: The budget drops whole memories, never fragments
  Given a token budget smaller than the assembled memories
  When a layer is assembled
  Then every memory in the result is present in full
  And a budget that fits everything drops nothing

@AC-4
Scenario: The ADR-091 weight bands are invariants, not preferences
  Given a memory at or above the always-include weight and a budget of zero
  When Layer 1 is assembled
  Then that memory is present
  And a memory below the budget-include weight is absent however relevant it is

@AC-5
Scenario: The assembled context reaches the prompt
  Given an agent whose context builder holds a context assembly policy
  When it builds the system prompt for a turn
  Then the assembled memory text is in that prompt
  And model-authored memory content cannot close a delimiter block it does not own

@AC-6
Scenario: One ranking formula, on one scale
  When a memory is scored
  Then the score is the ADR-080 part D product of weight and the summed terms
  And a bounded vector similarity can outrank a partial lexical match
```

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
