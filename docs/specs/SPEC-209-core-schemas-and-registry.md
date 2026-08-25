---
id: SPEC-209
title: "Pydantic agent schemas and the SCHEMA_REGISTRY dotted-path resolver"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-004
  - maistro-engine#ADR-005
implements:
  - maistro-engine#ADR-005
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - tests/agents/spec/test_schemas.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-209: Pydantic agent schemas and the SCHEMA_REGISTRY dotted-path resolver

## Context

Agent roles (Scout, Architect, Extractor, Validator, Planner, Coder, Reviewer) each
produce structured output that downstream stages (builders pipeline, A2A delegation,
orchestrator) must parse and validate without knowing the producing agent's concrete
type ahead of time. ADR-004 established the agent-spec convention; ADR-005 decided to
port a full set of typed Pydantic schemas plus a runtime, string-keyed registry so a
schema class can be looked up by dotted path (e.g. from a YAML agent definition or a
tool-call result) instead of being imported directly.

This spec documents the resulting design, already implemented in
`maistro.agents.spec.schemas`, as the canonical reference.

## Goals

- One typed Pydantic model per agent-role output shape (15 total).
- A single `SCHEMA_REGISTRY: dict[str, type[BaseModel]]` keyed by `"schemas.<ClassName>"`.
- `resolve_schema(dotted_path: str) -> type[BaseModel] | None` that checks the registry
  first, then falls back to `importlib` for classes not pre-registered, returning `None`
  (never raising) when nothing resolves.
- Backward compatibility with the pre-existing `PlanOutput`/`CodeOutput`/`ReviewOutput`/
  `SubTask`/`ConductorOutput` shapes in `agents/types.py`.

## Non-goals

- Migrating `ConductorOutput` out of `types.py` (explicitly deferred by ADR-005).
- Schema versioning/migration tooling — this spec covers only current-shape resolution.

## Decision

All schemas live in `src/maistro/agents/spec/schemas.py`:

```python
class PlanSubtask(BaseModel): id, description, depends_on, agent_role
class PlanOutput(BaseModel): subtasks, reasoning, estimated_tiers
class FileChange(BaseModel): path, action, description
class CodeOutput(BaseModel): files_modified, summary, tests_added
class ReviewScores(BaseModel): correctness, quality, safety, completeness, overall  # ge=0, le=10
class ReviewOutput(BaseModel): scores, selected_candidate, feedback, approved
class ScoutFile(BaseModel): path, lines, imports, exports, category
class ScoutOutput(BaseModel): files, total_lines, dependency_graph, god_files, summary
class ArchitectMapping(BaseModel): source, target, transforms, priority
class ArchitectNewFile(BaseModel): path, description, template
class ArchitectOutput(BaseModel): directory_structure, file_mappings, new_files, subtasks, reasoning
class CheckpointArchitectureOutput(BaseModel): checkpoint_goal, allowed_files, non_goals, invariants, review_focus, test_focus, summary
class ExtractorOutput(BaseModel): files_written, renames_applied, sanitizations, warnings, summary
class ValidatorCheck(BaseModel): name, passed, output
class ValidatorOutput(BaseModel): checks, all_passed, blocking_issues, summary

SCHEMA_REGISTRY: dict[str, type[BaseModel]]   # "schemas.PlanOutput" -> PlanOutput, ...
def resolve_schema(dotted_path: str) -> type[BaseModel] | None: ...
```

`ArchitectOutput.model_rebuild()` is called at module load so forward references
(e.g. `ArchitectMapping`/`ArchitectNewFile` used before their own definition order)
resolve correctly.

`resolve_schema` resolution order:
1. Direct lookup in `SCHEMA_REGISTRY` by exact dotted-path key.
2. `importlib` dynamic import fallback for paths not pre-registered (e.g. a caller's
   own module-qualified class), still returning the resolved type if importable.
3. `None` if neither path succeeds — callers must treat `None` as "no schema available",
   not an error.

Existing `agents/types.py` schemas are untouched and not part of `SCHEMA_REGISTRY`.

## Acceptance criteria

- [x] All 15 schema classes are importable from `maistro.agents.spec.schemas`
- [x] `SCHEMA_REGISTRY` covers all schemas with `"schemas.<ClassName>"` keys
- [x] `resolve_schema("schemas.ScoutOutput")` returns `ScoutOutput`
- [x] `resolve_schema("schemas.DoesNotExist")` returns `None`
- [x] `resolve_schema` dynamic importlib fallback resolves a custom class defined in a temp module
- [x] `ReviewScores` fields enforce `ge=0, le=10`
- [x] `ArchitectOutput.model_rebuild()` called so forward refs resolve

## Testing

Covered by `tests/agents/spec/test_schemas.py`:

| Test | Covers |
|---|---|
| `test_all_schemas_importable` | module imports cleanly |
| `test_schema_registry_keys` | all 15 schemas registered |
| `test_resolve_schema_known` | returns correct class |
| `test_resolve_schema_unknown` | returns `None`, no exception |
| `test_resolve_schema_dynamic_import` | importlib fallback |
| `test_review_scores_bounds` | ge/le validation |
| `test_plan_output_roundtrip` | serialize + deserialize |
| `test_scout_output_roundtrip` | serialize + deserialize |

## Open questions

- None — design is implemented and stable as of this writing.

## References

- [ADR-004: Agent spec](../adr/ADR-004-agent-spec.md)
- [ADR-005: Pydantic schemas + SCHEMA_REGISTRY](../adr/ADR-005-schemas.md)
- `packages/maistro-core/src/maistro/agents/spec/schemas.py`
