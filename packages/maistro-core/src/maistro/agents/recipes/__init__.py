"""Agent recipes package — declarative agent definitions (ADR-006)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from maistro.agents.spec.agent_spec import AgentRole
from maistro.graph.definitions import NodeTemplate
from maistro.graph.import_provenance import SOURCE_IMPORT_PROVENANCE, import_provenance

logger = logging.getLogger(__name__)

_DEFAULT_RECIPES_DIR = Path(__file__).parent / "yaml"
LEGACY_RECIPE_SNAPSHOT = "legacy_recipe_snapshot"


class AgentRecipe(BaseModel):
    name: str
    role: AgentRole
    description: str = ""
    prompt_name: str
    prompt_variants: list[str] = Field(default_factory=lambda: ["production"])
    result_schema: str | None = None
    tools: list[str] = Field(default_factory=list)
    min_tier: int = 2
    max_tier: int = 4
    temperature: float = 0.7
    max_tokens: int = 4096
    min_samples_before_selection: int = 20
    exploration_rate: float = 0.1


def agent_recipe_to_node_template(
    recipe: AgentRecipe,
    *,
    workspace_id: str,
    node_type: str,
    parameters: dict[str, Any] | None = None,
) -> NodeTemplate:
    """Project one legacy recipe into a canonical Workspace NodeTemplate.

    Recipe tool names are not canonical Capability Binding ids and the recipe's
    model-tier knobs do not prove a particular executable node kind. The caller
    therefore supplies ``node_type``/``parameters`` while the original reusable
    definition is retained as inert migration metadata. No permissions,
    policies or Binding ids are inferred from legacy content.
    """

    if not workspace_id.strip():
        raise ValueError("workspace_id must be a non-empty string")
    if not node_type.strip():
        raise ValueError("node_type must be a non-empty string")

    snapshot = recipe.model_dump(mode="json")
    provenance = import_provenance(
        snapshot,
        source_format="agent_recipe",
        source_definition="AgentRecipe",
        source_name=recipe.name,
    )
    return NodeTemplate(
        workspace_id=workspace_id,
        name=recipe.name,
        node_type=node_type,
        parameters=dict(parameters or {}),
        binding_ids=[],
        permissions={},
        policies={},
        metadata={
            SOURCE_IMPORT_PROVENANCE: provenance,
            LEGACY_RECIPE_SNAPSHOT: snapshot,
        },
    )


class RecipeRegistry:
    """Read/project compatibility adapter for legacy AgentRecipe definitions.

    Legacy YAML may still be consumed while callers migrate, and Persona
    expansion may register transient recipes in memory for the legacy spawner.
    Durable reusable definitions are canonical NodeTemplates/Personas, so this
    adapter intentionally has no YAML write API.
    """

    def __init__(self, recipes_dir: str | Path | None = None) -> None:
        self._dir = Path(recipes_dir) if recipes_dir else _DEFAULT_RECIPES_DIR
        self._cache: dict[str, AgentRecipe] = {}

    def get(self, name: str) -> AgentRecipe | None:
        if name in self._cache:
            return self._cache[name]
        return self._load_from_disk(name)

    def get_node_template(
        self,
        name: str,
        *,
        workspace_id: str,
        node_type: str,
        parameters: dict[str, Any] | None = None,
    ) -> NodeTemplate | None:
        """Resolve a legacy recipe and project it onto the canonical definition surface."""

        recipe = self.get(name)
        if recipe is None:
            return None
        return agent_recipe_to_node_template(
            recipe,
            workspace_id=workspace_id,
            node_type=node_type,
            parameters=parameters,
        )

    def list_recipes(self) -> list[AgentRecipe]:
        self._load_all()
        return list(self._cache.values())

    def register(self, recipe: AgentRecipe) -> None:
        """Register transient compatibility state; this never persists a definition."""

        self._cache[recipe.name] = recipe

    def _load_from_disk(self, name: str) -> AgentRecipe | None:
        if not self._dir.exists():
            return None
        filename = name.replace(".", "_") + ".yaml"
        path = self._dir / filename
        if path.exists():
            return self._parse_yaml(path)
        for yaml_path in self._dir.glob("*.yaml"):
            recipe = self._parse_yaml(yaml_path)
            if recipe and recipe.name == name:
                return recipe
        return None

    def _load_all(self) -> None:
        if not self._dir.exists():
            return
        for path in sorted(self._dir.glob("*.yaml")):
            self._parse_yaml(path)

    def _parse_yaml(self, path: Path) -> AgentRecipe | None:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not data or not isinstance(data, dict):
                return None
            recipe = AgentRecipe(**data)
            self._cache[recipe.name] = recipe
            return recipe
        except Exception as exc:
            logger.warning("Failed to parse recipe %s: %s", path, exc)
            return None


__all__ = [
    "LEGACY_RECIPE_SNAPSHOT",
    "SOURCE_IMPORT_PROVENANCE",
    "AgentRecipe",
    "RecipeRegistry",
    "agent_recipe_to_node_template",
]
