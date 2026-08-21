---
id: ADR-079
title: "LLM Provider / Model Registry, Routing, and Embeddings"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-05-30
substrate:
  - maistro-engine#ADR-007
  - maistro-engine#ADR-038
implements: []
related:
  - maistro-engine#ADR-012
  - maistro-engine#ADR-078
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-30
---

# ADR-079: LLM Provider / Model Registry, Routing, and Embeddings

**Status:** Proposed
**Date:** 2026-05-30
**Specifies** how the engine knows which models exist, how it picks one per task, and how it produces
the embeddings that ADR-012 stores — the model-selection substrate the ADR-007 scoring formula
assumes but never enumerates.

---

## Context

The ADR-007 scoring formula (`quality^(qw*p) / cost^cw` with speed bonuses) decides which model wins
a given task, but nothing says where the *candidate* models come from, who can change them, or how a
local P40-served model and a cloud provider sit in the same selection pool. ADR-078 makes config
DB-sourced and user-adjustable; ADR-038 owns fallback/circuit-breaking; ADR-012 owns the pgvector
store. What is undocumented is the **registry** of models and the **routing** that the scoring formula
runs over, plus the **embedding** path that feeds ADR-012. This ADR specifies all three.

## Decision

Three cooperating pieces in the Orchestration layer.

### Model Registry — the candidate pool

A registry of **local and cloud** models in one table: a local P40-served model alongside cloud
provider models, each with the metadata the ADR-007 formula needs (quality prior, cost, latency
profile, use-case tags, provider/endpoint). The registry is **config** — DB is the source of truth
(ADR-078) — and is **fully user-adjustable**: add, edit, and delete registry entries at runtime under
RBAC, no code deploy.

### Routing — default optimisation over cost × latency × use-case-fit

Routing picks the model **per task** by a **default optimisation over cost × latency ×
use-case-fit**, consistent with the ADR-007 scoring formula (`quality^(qw*p) / cost^cw` + speed
bonuses). The optimisation weights and the routing rules live in config (DB source of truth, ADR-078)
and are **fully user-adjustable** (add/edit/delete routing entries). When the chosen model is
unavailable or fails, selection falls through a **fallback chain via ADR-038** (next-best candidate,
circuit-broken models skipped).

```python
class ModelRegistry(Protocol):
    def candidates(self, *, use_case: str | None = None) -> list[ModelEntry]: ...

class Router(Protocol):
    def pick(self, task: Task) -> ModelEntry: ...        # default optimise cost × latency × fit
    def fallback_chain(self, task: Task) -> list[ModelEntry]: ...   # ADR-038

class ModelEntry(BaseModel):
    id: str
    kind: Literal["local", "cloud"]
    endpoint: str
    quality: float
    cost_per_1k: float
    latency_ms: float
    use_case_tags: list[str]
```

### Embeddings — LiteLLM first, local sentence-transformer fallback

Embeddings are produced via **LiteLLM** (whatever embedding model is configured there). If no LiteLLM
embedding model is available, the engine **falls back to a local sentence-transformer** — something
small that runs on anything. Vectors are stored in **pgvector (ADR-012)**.

Every embedding is **stamped with its model version**. A model change does not invalidate existing
vectors inline; instead it triggers a background **batch re-embed**, run **overnight at batch pricing**
(cost-optimised), that rewrites affected vectors and updates their version stamp.

```python
class Embedder(Protocol):
    def embed(self, text: str) -> Embedding: ...         # LiteLLM, else local sentence-transformer

class Embedding(BaseModel):
    vector: list[float]
    model_version: str                                   # stamped; drives batch re-embed
```

## Acceptance criteria

- [ ] The registry holds both local (e.g. P40-served) and cloud models in one pool; entries are
      DB-sourced (ADR-078) and add/edit/delete-able at runtime under RBAC with no code deploy.
- [ ] Routing picks a model per task by the default optimisation over cost × latency × use-case-fit,
      consistent with the ADR-007 formula; routing weights/entries are user-adjustable in config.
- [ ] When the chosen model is unavailable or failing, selection falls through an ADR-038 fallback
      chain rather than erroring.
- [ ] Embeddings are produced via LiteLLM when an embedding model is configured there; with none
      configured, the local sentence-transformer fallback is used.
- [ ] Vectors are written to pgvector (ADR-012) and every embedding carries a model-version stamp.
- [ ] Changing the embedding model enqueues a background batch re-embed that runs overnight at batch
      pricing and updates the version stamp; existing vectors are not invalidated inline.

## Consequences

- The ADR-007 scoring formula gets a concrete, user-editable candidate pool to score over.
- Operators tune models and routing from config (ADR-078) without redeploys; mechanism stays in code.
- Embedding never hard-fails on a missing cloud model — the local sentence-transformer is the floor.
- Embedding-model changes are eventually-consistent: vectors carry a version and are re-embedded in a
  cheap overnight batch rather than synchronously.

## Out of scope

- The concrete optimisation weights / default θ for cost × latency × fit (a tuning detail; follow-up SPEC).
- The specific local sentence-transformer model choice and its packaging.
- The pgvector schema and index tuning — ADR-012.
- Multi-tenant registry partitioning — Stronghold (ADR-019).
