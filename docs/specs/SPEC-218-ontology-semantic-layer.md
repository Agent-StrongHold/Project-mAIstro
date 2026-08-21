---
id: SPEC-218
title: "Ontology v1.0: Semantic facet types, registry, and InMemoryOntology"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-06-20
substrate:
  - maistro-engine#ADR-005
  - maistro-engine#ADR-031
  - maistro-engine#ADR-036
implements:
  - maistro-engine#ADR-036
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - tests/ontology/test_registry.py
  - tests/ontology/test_types.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-218: Ontology v1.0: Semantic facet types, registry, and InMemoryOntology

## Context

Shared types lived in three disconnected places — dataclasses in `types/`,
Pydantic wire schemas, and SQLAlchemy DB models — with no first-class typed
object meaning the same thing across products. ADR-036 decided to ship a
minimal Ontology layer (mirroring Palantir AIP's Semantic/Kinetic/Dynamic
facet terminology) with **only the Semantic facet implemented in v1.0**;
Kinetic and Dynamic are reserved for later product-driven specs.

## Goals

- A typed `OntologyEntity` with a stable `kind` slug, time-ordered UUID,
  and a `facets` dict keyed by `Facet` (only `SEMANTIC` populated in v1.0).
- A `register(kind, model)` API that's idempotent for identical
  re-registration and raises on conflicting re-registration.
- `get`/`query`/`upsert` operations validated against the registered
  Pydantic model at write time.
- An `InMemoryOntology` reference implementation satisfying the `Ontology`
  Protocol, suitable for tests and engine boot without Postgres.

## Non-goals

- Kinetic facet (actions with pre/post-condition contracts) — deferred,
  not implemented.
- Dynamic facet (state transitions, version history, revision queries) —
  deferred; `revision` field exists on `OntologyEntity` but nothing bumps
  it yet.
- `PostgresOntology` — explicitly deferred per `protocols.py`'s docstring;
  only the in-memory implementation exists.
- Cross-tenant ontology sharing and graph traversal — out of scope per
  ADR-036.

## Decision

`maistro/ontology/types.py`:

```python
class Facet(StrEnum):
    SEMANTIC = "semantic"
    KINETIC = "kinetic"   # reserved
    DYNAMIC = "dynamic"   # reserved

class OntologyEntity(BaseModel):
    id: UUID = Field(default_factory=uuid4)   # UUIDv7-style, time-ordered
    kind: str
    revision: int = 1
    facets: dict[Facet, dict[str, Any]] = Field(default_factory=dict)

    def get_semantic(self) -> dict[str, Any]: ...
    def with_semantic(self, data: dict[str, Any]) -> OntologyEntity: ...  # non-mutating
```

`maistro/ontology/protocols.py`:

```python
@runtime_checkable
class Ontology(Protocol):
    def register(self, kind: str, semantic: type[BaseModel]) -> None: ...
    def get(self, entity_id: UUID) -> OntologyEntity | None: ...
    def query(self, kind: str, **filters: object) -> list[OntologyEntity]: ...
    def upsert(self, entity: OntologyEntity) -> OntologyEntity: ...
```

`maistro/ontology/registry.py` provides `InMemoryOntology`, the sole
implementation as of this spec. `register()` is idempotent for an
identical model and raises `KindAlreadyRegisteredError` on a conflicting
re-registration; `query()` raises `KindNotRegisteredError` for an unknown
`kind`; `upsert()` validates the entity's `SEMANTIC` facet against the
registered model and returns the validated (coerced) form. `get()` returns
a deep copy so caller mutation can't desync stored state.

Memory records gaining an `entity_id: UUID | None` field (per ADR-036's
"memory records gain a typed home" goal) is **not yet implemented** — no
such field exists on `MemoryEntry`/`EpisodicMemory` as of this writing.

## Acceptance criteria

- [x] `OntologyEntity` has a UUID `id`, `kind` slug, `revision` int, and
      `facets: dict[Facet, dict]`
- [x] `register(kind, T)` is idempotent for re-registration with the same
      model
- [x] `register(kind, T)` raises on re-registration with a different model
- [x] `get(id)` returns `None` for an absent entity, and a deep copy
      otherwise
- [x] `query(kind, **filters)` raises for an unregistered `kind`
- [x] `upsert()` validates the SEMANTIC facet against the registered model
- [x] `InMemoryOntology` satisfies `isinstance(..., Ontology)`
- [ ] Memory records carry an optional `entity_id` pointing at a registered
      ontology entity (ADR-036 goal, not yet implemented)

## Testing

Covered by `tests/ontology/test_registry.py` and `tests/ontology/test_types.py`.

## Open questions

- Whether/when to wire `entity_id` into `MemoryEntry`/`EpisodicMemory` so
  episodic queries can filter by entity kind, per ADR-036's stated goal —
  not yet scheduled.
- `PostgresOntology` and the Kinetic/Dynamic facets remain explicitly
  deferred to future product-driven specs, per ADR-036's "Out of scope."

## References

- [ADR-005: Pydantic schemas + SCHEMA_REGISTRY](../adr/ADR-005-schemas.md)
- [ADR-036: Ontology / Semantic Object Layer](../adr/ADR-036-ontology-semantic-object-layer.md)
- `packages/maistro-core/src/maistro/ontology/types.py`
- `packages/maistro-core/src/maistro/ontology/protocols.py`
- `packages/maistro-core/src/maistro/ontology/registry.py`
