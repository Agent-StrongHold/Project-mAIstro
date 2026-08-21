---
id: ADR-005
title: Pydantic schemas + SCHEMA_REGISTRY
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-04-26
substrate:
  - maistro-engine#ADR-004
implements: []
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
history:
  - status: Proposed
    date: 2026-04-26
  - status: Accepted
    date: 2026-04-26
---

# ADR-005: Pydantic schemas + SCHEMA_REGISTRY

**Status:** Accepted
**Date:** 2026-04-26
**Tranche:** T1
**Depends on:** ADR-004

---

## Context

maistro-engine has basic `PlanOutput`/`CodeOutput`/`ReviewOutput` in `agents/types.py` but lacks schemas for Scout, Architect, Extractor, and Validator agents. There is no registry for runtime schema lookup by dotted-path string.

## Decision

Port all schemas into `src/maistro/agents/spec/schemas.py` plus `SCHEMA_REGISTRY` dict and `resolve_schema(dotted_path)`.

Existing `types.py` schemas (`PlanOutput`, `CodeOutput`, `ReviewOutput`, `SubTask`, `ConductorOutput`) are kept unchanged for backward compat. The new schemas are additive and richly typed.

## Interface

```python
# src/maistro/agents/spec/schemas.py

class PlanSubtask(BaseModel): id, description, depends_on, agent_role
class PlanOutput(BaseModel): subtasks, reasoning, estimated_tiers
class FileChange(BaseModel): path, action, description
class CodeOutput(BaseModel): files_modified, summary, tests_added
class ReviewScores(BaseModel): correctness, quality, safety, completeness, overall  # all 0–10
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

SCHEMA_REGISTRY: dict[str, type[BaseModel]]  # "schemas.PlanOutput" → PlanOutput, ...
def resolve_schema(dotted_path: str) -> type[BaseModel] | None
```

## Acceptance criteria

- [ ] All 15 schema classes are importable from `maistro.agents.spec.schemas`
- [ ] `SCHEMA_REGISTRY` covers all schemas with "schemas.<ClassName>" keys
- [ ] `resolve_schema("schemas.ScoutOutput")` returns `ScoutOutput`
- [ ] `resolve_schema("schemas.DoesNotExist")` returns `None`
- [ ] `resolve_schema` dynamic importlib fallback resolves a custom class defined in a temp module
- [ ] `ReviewScores` fields enforce `ge=0, le=10`
- [ ] `ArchitectOutput.model_rebuild()` called so forward refs resolve

## Test plan

| Test | Covers |
|---|---|
| `test_all_schemas_importable` | module imports cleanly |
| `test_schema_registry_keys` | all 15 schemas registered |
| `test_resolve_schema_known` | returns correct class |
| `test_resolve_schema_unknown` | returns None, no exception |
| `test_resolve_schema_dynamic_import` | importlib fallback |
| `test_review_scores_bounds` | ge/le validation |
| `test_plan_output_roundtrip` | serialize + deserialize |
| `test_scout_output_roundtrip` | serialize + deserialize |

## Out of scope

`ConductorOutput` migration (left in `types.py`).

## Source references

- `Project_mAIstro/conductor/orchestrator/agents/schemas.py`
