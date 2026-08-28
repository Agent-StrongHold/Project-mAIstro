"""Agent recipes package — declarative agent definitions (ADR-006)."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from maistro.agents.spec.agent_spec import AgentRole
from maistro.graph.definitions import NodeTemplate

logger = logging.getLogger(__name__)

_DEFAULT_RECIPES_DIR = Path(__file__).parent / "yaml"
SOURCE_IMPORT_PROVENANCE = "source_import_provenance"
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
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    provenance = {
        "source_format": "agent_recipe",
        "source_definition": "AgentRecipe",
        "source_name": recipe.name,
        "source_hash": hashlib.sha256(encoded).hexdigest(),
    }
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
    def __init__(self, recipes_dir: str | Path | None = None) -> None:
        self._dir = Path(recipes_dir) if recipes_dir else _DEFAULT_RECIPES_DIR
        self._cache: dict[str, AgentRecipe] = {}

    def get(self, name: str) -> AgentRecipe | None:
        if name in self._cache:
            return self._cache[name]
        return self._load_from_disk(name)

    def list_recipes(self) -> list[AgentRecipe]:
        self._load_all()
        return list(self._cache.values())

    def register(self, recipe: AgentRecipe) -> None:
        self._cache[recipe.name] = recipe

    def save(self, recipe: AgentRecipe) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        filename = recipe.name.replace(".", "_") + ".yaml"
        path = self._dir / filename
        data = recipe.model_dump(exclude_defaults=True)
        data["role"] = recipe.role.value
        path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
        self._cache[recipe.name] = recipe
        return path

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
