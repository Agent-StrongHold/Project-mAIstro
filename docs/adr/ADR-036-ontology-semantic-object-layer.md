---
id: ADR-036
title: Ontology / Semantic Object Layer
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-07
accepted: 2026-05-07
substrate:
  - maistro-engine#ADR-005
  - maistro-engine#ADR-031
implements: []
related:
  - maistro-engine#ADR-030
  - maistro-engine#ADR-034
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
    date: 2026-05-07
  - status: Accepted
    date: 2026-05-07
---

# ADR-036: Ontology / Semantic Object Layer

## Context

The framework comparison against Palantir AIP surfaced one architectural gap none of the four repos cover: a typed semantic-object layer (Palantir calls this Ontology, with Semantic / Kinetic / Dynamic facets). Today our shared types live in `types/` as dataclasses, our wire schemas are Pydantic, our DB shapes are SQLAlchemy, and agents share state through ad-hoc memory records. There is no first-class typed object that means *the same thing* across products.

The cost of not having one shows up in three places:

1. Cross-product agent portability (mAIstro agent → Stronghold tenant tool) requires re-mapping every concept
2. Approval workflows (HITL, `Project_mAIstro#SPEC-158 human-as-node`) have no shared object to vote on
3. Reasoning agents have no shared world model — they reconstruct one from memory each invocation

## Decision

Engine ships a minimal Ontology layer at `src/maistro/ontology/` with three facets, mirroring Palantir AIP terminology so the boundary is intentional:

- **Semantic** — what an object *is*. Typed entities (`Person`, `Task`, `Document`, `Skill`, `Budget`) with typed relationships. Backed by Pydantic for validation and SQLAlchemy for persistence.
- **Kinetic** — what an object *does*. Actions an entity exposes, with pre/post-condition contracts (per ADR-032).
- **Dynamic** — how an object *evolves*. State transitions, version history, derivation lineage.

Products subscribe to the ontology by registering their domain entities:

- `Project_mAIstro` adds `Household`, `User`, `Channel`
- `AgentTuring` adds `SelfModel`, `Mood`, `Drive`
- `stronghold` adds `Tenant`, `Policy`, `AuditEvent`

### v1.0 scope

v1.0 ships **Semantic only**: Pydantic types, SQLAlchemy persistence, an in-process registry, and a `kind:` discriminator on memory records that lets episodic memory point at ontology entities by ID. Kinetic and Dynamic are spec'd but not implemented until a product spec demands them.

### Interface sketch

```python
class OntologyEntity(BaseModel):
    id: UUID
    kind: str            # registered entity type
    revision: int = 1    # bumps on Dynamic facet edits (v2.0)
    facets: dict[Facet, dict] = Field(default_factory=dict)

class Ontology(Protocol):
    def register(self, kind: str, semantic: type[BaseModel]) -> None: ...
    def get(self, entity_id: UUID) -> OntologyEntity: ...
    def query(self, kind: str, **filters: object) -> list[OntologyEntity]: ...
    def upsert(self, entity: OntologyEntity) -> OntologyEntity: ...
```

Memory records gain an optional `entity_id: UUID | None` field. When set, the record refers to a registered ontology entity — the typed home that today's records lack.

### Boundary contracts

- Every registered `kind` has a Pydantic model. Validation runs on `upsert`.
- `kind:` is a stable string slug (no renames without a migration).
- `id:` is UUIDv7 (time-ordered) so the registry is naturally sorted.

### Behavioral contracts

- `register(kind, T)` is idempotent; re-registering the same `kind` with a non-equivalent `T` raises.
- `get(id)` returns the latest revision; querying historical revisions is a v2.0 capability (Dynamic facet).
- `query` is read-consistent within a single call.

## Consequences

- Cross-product agent portability becomes possible at the *type* level. Two agents agreeing on `kind="Task"` agree on the schema, regardless of which product they run in.
- Memory records gain a typed home. Episodic queries can filter by entity kind, not just by free-text search.
- The engine grows a new module that all three products will eventually depend on. v1.0 keeps the surface minimal so the cost is bounded.
- Until ontology is in active use, plain dataclasses in `types/` remain valid for shared types. Migration is opt-in per product spec.
- Stronghold's multi-tenant catalog (ADR-035) gains a natural upgrade path: tenant-scoped ontology entities are a v2.0 capability.

## Out of scope

- Kinetic and Dynamic facet implementations — separate engine ADRs when spec'd.
- Cross-tenant ontology sharing — stronghold concern (separate ADR).
- Ontology versioning policy (schema migration) — separate engine ADR.
- Graph queries / traversal language — v2.0+.
