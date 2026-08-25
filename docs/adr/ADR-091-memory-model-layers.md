---
id: ADR-091
title: Memory model reconciliation — storage types vs context assembly layers
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-06-02
accepted: null
substrate:
  - maistro-engine#ADR-034
  - maistro-engine#ADR-013
  - maistro-engine#ADR-016
implements: []
related:
  - maistro-engine#SPEC-177
  - maistro-engine#SPEC-189
  - maistro-engine#SPEC-193
  - maistro-engine#ADR-071
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Memory
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-02
  - status: Implemented
---

# ADR-091: Memory model reconciliation

## Context

The codebase has accumulated multiple memory abstractions that serve different
purposes but have never been formally distinguished. This causes confusion about
which to use, where to extend, and how they relate.

### Current models (inventory)

**1. Storage types** (`maistro.types.memory`, `maistro.memory.*`)

Persistent records of what the system has learned or experienced:

| Type | What it stores |
|------|---------------|
| `EpisodicMemory` | 7-tier weighted observations (OBSERVATION → WISDOM) |
| `Learning` | Self-improving corrections from tool call patterns, scoped |
| `Outcome` | Per-task completion record with cost, eval score, thumb signal |
| `SkillMutation` | Record of a skill rewrite promoted from a learning |

Scopes: `GLOBAL → ORGANIZATION → TEAM → USER → AGENT → SESSION`

**2. WorkingMemoryProtocol** (SPEC-177 port target)

Per-execution-run storage for the graph engine: traces, optimization signals,
node configs. Ephemeral relative to the storage types above — relevant only for
the duration of a graph run and its immediate optimizer follow-up.

**3. Conductor Layer 0-4 assembly taxonomy** (Conductor snapshot; not yet ported)

A numbered hierarchy that describes *how memory is assembled into an LLM request*,
not what is stored:

| Layer | Content | Lifecycle |
|-------|---------|-----------|
| 0 | Pinned project constraints (markdown) | Static per project context load; invalidates KV cache on change (SPEC-193) |
| 1 | Working memory for the active task | Ephemeral; cleared between tasks |
| 2 | Compressed conversation history | Rolling window (SPEC-189) |
| 3 | JSONL changelog of past decisions | Append-only; queryable by project |
| 4 | Knowledge graph | Deferred (see DECISION-BACKLOG) |

**4. maistro-turing memory bridge** (`maistro_turing.bridge`)

A product-specific projection that reads `EpisodicMemory` and `Learning` from
maistro-core and maps them into Turing's mood, HEXACO personality, and drive
systems. Not a new storage layer — a consumer of layers already defined.

### The confusion

The Conductor snapshot refers to "Layer 1 working memory" and "Layer 2 history"
as if they are storage types alongside episodic memory. They are not. They are
*slots in a context assembly policy* — positional arguments to the LLM prompt,
filled from existing storage systems. Conflating the two leads to questions like
"should I store this in episodic memory or layer 1?" The answer is: those are
different dimensions entirely.

## Decision

Adopt a **two-level separation**:

### Level 1 — Storage types (what is persisted)

Unchanged. `EpisodicMemory`, `Learning`, `Outcome`, `SkillMutation` remain the
canonical persistent stores, governed by ADR-013/016/034. The `WorkingMemoryProtocol`
(SPEC-177) is added as a fifth store: ephemeral per graph-run, backed by in-memory
default with optional persistent adapter.

#### The 7-tier episodic system as a retrieval filter

`EpisodicMemory.tier` (`MemoryTier`) is a **weight/confidence axis within the
storage layer** — it is not an assembly layer. The tiers in ascending weight order:

| Tier | Weight bounds | Meaning |
|------|--------------|---------|
| `OBSERVATION` | 0.1 – 0.5 | Raw, unconfirmed impression |
| `HYPOTHESIS` | 0.2 – 0.6 | Candidate explanation, needs validation |
| `OPINION` | 0.3 – 0.8 | Held view, some evidence |
| `LESSON` | 0.5 – 0.9 | Confirmed pattern from experience |
| `REGRET` | 0.6 – 1.0 | Structurally unforgettable; weight floor 0.6 |
| `AFFIRMATION` | 0.6 – 1.0 | Positively reinforced success pattern |
| `WISDOM` | 0.9 – 1.0 | Near-invariant; decays only under strong contradiction |

The tier determines **inclusion priority when episodic memories are retrieved for
context assembly**. The rules for the default `ContextAssemblyPolicy`:

- **Always include** (weight ≥ 0.6): REGRET, AFFIRMATION, WISDOM — regardless of
  token budget. These are the memories the system must not forget.
- **Include if budget allows** (weight 0.3–0.59): OPINION, LESSON — ranked by
  `weight × recency` descending, truncated when the layer token budget is reached.
- **Exclude by default** (weight < 0.3): OBSERVATION, HYPOTHESIS — omitted unless
  the caller explicitly requests them (e.g. for consolidation passes).

Token budgets per layer are set in `ContextAssemblyPolicy` configuration; defaults
are implementation-defined. The weight thresholds above are invariants of this ADR,
not configuration.

This answers the question "which episodic memories appear in which assembly layer?":
retrieved episodic memories are candidates for **Layer 1** (task context) and
potentially **Layer 3** (project changelog, if relevant to the current project).
The tier/weight determines which ones survive the budget cut. Layer 0 (constraints)
and Layer 2 (session history) do not draw from `EpisodicMemory`.

### Level 2 — Context assembly layers (how storage is assembled into an LLM request)

Introduce a `ContextAssemblyPolicy` that maps the Layer 0-4 taxonomy to concrete
sources from Level 1:

| Layer | Assembly source | Episodic tier filter |
|-------|----------------|----------------------|
| 0 | `Project.constraints_text` | — (not from episodic store) |
| 1 | `WorkingMemoryProtocol.load_traces(run_id)` + scoped `EpisodicMemory` | Weight ≥ 0.6 always; 0.3–0.59 if budget; < 0.3 excluded |
| 2 | `SessionStore` compressed history (SPEC-189) | — (not from episodic store) |
| 3 | `Outcome` store filtered by `project_id`, recent N; high-tier episodic summaries | Weight ≥ 0.9 (WISDOM) for project-scoped episodic inclusion |
| 4 | Knowledge graph | — (deferred) |

Notes:
- Layer 0: loaded at project context load; content hash triggers KV cache
  invalidation (SPEC-193). Always included, never truncated.
- Layer 1: the primary "what do I know right now?" slot. Active task description
  + high-confidence episodic memories scoped to the current agent/session.
  For single-pass conductor this is the current task description only.
- Layer 2: rolling compressed conversation window per SPEC-189; replaces raw
  message array for long sessions.
- Layer 3: recent `Outcome` records (what did this project do before?) plus
  WISDOM-tier episodic memories that are project-scoped — the system's "memory
  of lessons learned on this project".
- Layer 4: returns `""` until the knowledge graph spec is implemented.

`ContextAssemblyPolicy` is a protocol (abstract interface), not a concrete class, so
different products can implement different assembly strategies. The conductor uses the
default Layer 0-4 implementation; other callers (Stronghold, canvas) may supply their
own.

#### `ContextAssemblyPolicy` interface

```python
class ContextAssemblyPolicy(Protocol):
    async def layer0(self, project_id: str) -> str:
        """Pinned project constraints text. Always included; drives KV cache key."""

    async def layer1(self, run_id: str, agent_id: str, session_id: str) -> str:
        """Active task context: working memory traces + high-confidence episodic
        memories scoped to this agent/session (weight ≥ 0.6, scope ≤ AGENT)."""

    async def layer2(self, session_id: str, budget_tokens: int) -> str:
        """Compressed conversation history (SPEC-189 rolling window)."""

    async def layer3(self, project_id: str, n: int = 20) -> str:
        """Project changelog: recent Outcome records + WISDOM-tier episodic
        memories scoped to this project."""

    async def layer4(self, project_id: str) -> str:
        """Knowledge graph context. Returns '' until implemented."""

    async def assemble(
        self,
        project_id: str,
        run_id: str,
        agent_id: str,
        session_id: str,
        budget_tokens: int,
    ) -> str:
        """Concatenate layers 0-4 in order, respecting budget_tokens total."""
```

The `budget_tokens` argument is the total context budget available for all layers
combined. Layer 0 is never truncated; layers 1-3 are truncated in reverse priority
(layer 3 first) when the budget is tight. Layer 4 is included only if space remains.

#### Scope + tier interaction

Tier weight determines *how strongly* to weight a memory; scope determines *which agent
or session it belongs to*. Both filters apply during retrieval:

- Layer 1 includes episodic memories where `scope ∈ {AGENT, SESSION}` AND `scope` matches
  the current `agent_id` / `session_id`. A WISDOM-tier memory belonging to a different
  agent is **excluded from Layer 1** even though its weight ≥ 0.6.
- Layer 3 includes episodic memories where `scope ∈ {USER, TEAM, AGENT}` AND `project_id`
  matches. WISDOM-tier memories from the same project but a different user are included
  (shared project-level wisdom); session-scoped memories are excluded.
- GLOBAL-scoped memories (system-wide invariants) are included in Layer 0's constraints
  text, not retrieved dynamically.

The rule of thumb: **tier controls weight; scope controls visibility**. A memory must
pass both filters to appear in a given layer.

### Naming

- **"working memory"** in code means `WorkingMemoryProtocol` (per SPEC-177). Do NOT
  use "working memory" to mean "Layer 1" in prose — say "Layer 1 (task context)" to
  avoid ambiguity.
- **"memory layer"** always refers to the assembly taxonomy. Storage types are called
  **"memory stores"** or by their type name.

## Consequences

- The Layer 0-4 taxonomy is now a first-class concept in docs. Existing storage types
  are unchanged.
- `ContextAssemblyPolicy` protocol needs to be added to `maistro.protocols` and wired
  through `container.py`.
- `SPEC-177` graph execution wires `WorkingMemoryProtocol` as Layer 1 for graph runs.
- `SPEC-193` prefix cache manager receives Layer 0 text as the `layer0_text` field
  in `POST /v1/project/load`. The orchestrator is responsible for reading
  `Project.constraints_text` and passing it as `layer0_text`. The gateway treats it
  as an opaque string for hashing purposes only.
- `SPEC-189` rolling context assembly fills Layer 2.
- Layer 4 (knowledge graph) returns `""` until the knowledge graph spec is implemented.
- maistro-turing bridge is unaffected — it reads from Level 1 storage types directly.

## Out of scope

- Changing the `EpisodicMemory`, `Learning`, `Outcome`, `SkillMutation` schemas,
  except for an additive `EpisodicMemory.project_id: str = ""` field (added by
  SPEC-244) needed to make Layer 3's "project changelog" claim true rather than
  approximated by team/agent scope — this is the one exception to this ADR's
  original no-schema-change stance, decided during SPEC-244's implementation.
- Memory consolidation policy (when memories merge, decay schedule) — see
  DECISION-BACKLOG ☐ "Memory consolidation ADR".
- Vector store / semantic search for Layer 3 or 4 — separate ADR.
- Knowledge graph implementation — separate SPEC (see DECISION-BACKLOG).
