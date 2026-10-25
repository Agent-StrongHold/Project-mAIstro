---
id: ADR-006
title: AgentRecipe + RecipeRegistry
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-04-26
substrate:
  - maistro-engine#ADR-004
  - maistro-engine#ADR-005
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - tests/agents/recipes/test_registry.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-26
  - status: Accepted
    date: 2026-04-26
---

# ADR-006: AgentRecipe + RecipeRegistry

**Status:** Accepted
**Date:** 2026-04-26
**Tranche:** T1
**Depends on:** ADR-004, ADR-005

---

## Context

Agents are currently wired by hard-coded prompt strings in `agents/prompts.py`. There is no way to A/B test prompts, declare per-role model constraints, or evolve agent definitions without code changes.

## Decision

Port `AgentRecipe` (Pydantic model) and `RecipeRegistry` (YAML loader + cache) into `src/maistro/agents/recipes/__init__.py`. Seed with YAML files for the 7 core roles under `src/maistro/agents/recipes/yaml/`.

## Interface

```python
class AgentRecipe(BaseModel):
    name: str                           # e.g. "coder.generate"
    role: AgentRole
    description: str = ""
    prompt_name: str
    prompt_variants: list[str] = ["production"]
    result_schema: str | None = None    # dotted path into SCHEMA_REGISTRY
    tools: list[str] = []
    min_tier: int = 2
    max_tier: int = 4
    temperature: float = 0.7
    max_tokens: int = 4096
    min_samples_before_selection: int = 20
    exploration_rate: float = 0.1

class RecipeRegistry:
    def __init__(self, recipes_dir: str | Path | None = None) -> None: ...
    def get(self, name: str) -> AgentRecipe | None: ...
    def list_recipes(self) -> list[AgentRecipe]: ...
    def register(self, recipe: AgentRecipe) -> None: ...
    def save(self, recipe: AgentRecipe) -> Path: ...
```

Seeded YAMLs (one per role, minimal config):
- `planner_decompose.yaml` → `schemas.PlanOutput`
- `coder_generate.yaml` → `schemas.CodeOutput`
- `reviewer_score.yaml` → `schemas.ReviewOutput`
- `scout_analyze.yaml` → `schemas.ScoutOutput`
- `architect_design.yaml` → `schemas.ArchitectOutput`
- `extractor_transform.yaml` → `schemas.ExtractorOutput`
- `validator_check.yaml` → `schemas.ValidatorOutput`

## Acceptance criteria

- [ ] `RecipeRegistry().get("coder.generate")` loads from bundled YAML
- [ ] `RecipeRegistry(recipes_dir=tmp)` loads YAMLs from custom dir
- [ ] Malformed YAML file logs a warning and returns `None`, does not raise
- [ ] `registry.register(recipe)` makes recipe available via `get()`
- [ ] `registry.save(recipe)` writes YAML; subsequent `get()` returns it
- [ ] `registry.list_recipes()` returns all recipes from the YAML dir

## Test plan

| Test | Covers |
|---|---|
| `test_registry_loads_bundled_recipes` | default recipes dir |
| `test_registry_custom_dir` | custom recipes_dir |
| `test_registry_malformed_yaml_warns` | graceful degradation |
| `test_registry_programmatic_register` | register + get |
| `test_registry_save_roundtrip` | save + get |
| `test_recipe_result_schema_resolves` | dotted-path schema field is valid |

## Out of scope

Langfuse prompt sync (Project_mAIstro specific). Hot-reload (T5 skill catalog).

## Source references

- `Project_mAIstro/conductor/orchestrator/agents/recipe.py`
- `Project_mAIstro/conductor/orchestrator/agents/recipes/` (YAML files)
