"""Tests for AgentRecipe + RecipeRegistry (ADR-006)."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from maistro.agents.recipes import AgentRecipe, RecipeRegistry, agent_recipe_to_node_template
from maistro.agents.spec.agent_spec import AgentRole
from maistro.agents.spec.schemas import resolve_schema


class TestAgentRecipe:
    def test_recipe_defaults(self) -> None:
        recipe = AgentRecipe(
            name="coder.generate",
            role=AgentRole.CODER,
            prompt_name="coder.generate",
        )
        assert recipe.prompt_variants == ["production"]
        assert recipe.min_tier == 2
        assert recipe.exploration_rate == 0.1

    def test_recipe_result_schema_resolves(self) -> None:
        recipe = AgentRecipe(
            name="coder.generate",
            role=AgentRole.CODER,
            prompt_name="coder.generate",
            result_schema="schemas.CodeOutput",
        )
        assert recipe.result_schema is not None
        cls = resolve_schema(recipe.result_schema)
        assert cls is not None


class TestRecipeRegistry:
    def test_loads_bundled_recipes(self) -> None:
        registry = RecipeRegistry()
        recipe = registry.get("coder.generate")
        assert recipe is not None
        assert recipe.role == AgentRole.CODER

    def test_bundled_recipes_have_result_schema(self) -> None:
        registry = RecipeRegistry()
        for name in ("scout.analyze", "architect.design", "validator.check"):
            recipe = registry.get(name)
            assert recipe is not None, f"Missing bundled recipe: {name}"
            assert recipe.result_schema is not None

    def test_custom_dir(self, tmp_path: Path) -> None:
        recipe = AgentRecipe(
            name="test.custom",
            role=AgentRole.CODER,
            prompt_name="test.custom",
        )
        data = recipe.model_dump(exclude_defaults=True)
        data["role"] = recipe.role.value
        (tmp_path / "test_custom.yaml").write_text(yaml.dump(data), encoding="utf-8")

        registry = RecipeRegistry(recipes_dir=tmp_path)
        found = registry.get("test.custom")
        assert found is not None
        assert found.name == "test.custom"

    def test_malformed_yaml_warns_not_raises(self, tmp_path: Path, caplog) -> None:
        (tmp_path / "bad.yaml").write_text(":: invalid: yaml: [", encoding="utf-8")
        registry = RecipeRegistry(recipes_dir=tmp_path)
        with caplog.at_level(logging.WARNING):
            result = registry.get("bad")
        assert result is None

    def test_programmatic_register(self) -> None:
        registry = RecipeRegistry()
        recipe = AgentRecipe(
            name="my.special",
            role=AgentRole.PLANNER,
            prompt_name="my.special",
        )
        registry.register(recipe)
        found = registry.get("my.special")
        assert found is recipe

    def test_custom_recipe_projects_to_canonical_template(self, tmp_path: Path) -> None:
        recipe = AgentRecipe(
            name="saved.recipe",
            role=AgentRole.REVIEWER,
            prompt_name="saved.prompt",
            result_schema="schemas.ReviewOutput",
        )
        data = recipe.model_dump(exclude_defaults=True)
        data["role"] = recipe.role.value
        (tmp_path / "saved_recipe.yaml").write_text(yaml.dump(data), encoding="utf-8")

        registry = RecipeRegistry(recipes_dir=tmp_path)
        resolved = registry.get("saved.recipe")
        assert resolved is not None
        template = agent_recipe_to_node_template(
            resolved,
            workspace_id="workspace-1",
            node_type="agent.compatibility",
        )

        assert template.workspace_id == "workspace-1"
        assert template.metadata["source_import_provenance"]["source_format"] == "agent_recipe"
        assert template.metadata["legacy_recipe_snapshot"]["result_schema"] == "schemas.ReviewOutput"

    def test_list_recipes_returns_all(self) -> None:
        registry = RecipeRegistry()
        recipes = registry.list_recipes()
        names = {r.name for r in recipes}
        assert "coder.generate" in names
        assert "planner.decompose" in names

    def test_missing_recipe_returns_none(self) -> None:
        registry = RecipeRegistry()
        assert registry.get("does.not.exist") is None
